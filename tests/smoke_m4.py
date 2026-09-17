"""M4 冒烟测试（离屏运行，临时数据库隔离）：
- 周汇总统计准确性（完成/进行中/记录/图片/失败/超时）
- 规划项拖拽排序（reorder_date / set_item_date_order 持久化）
- 一键转实验数据一致性（experiments 行 + 提醒武装 + 回写 linked_experiment_id）
- 周报导出 Markdown / HTML 文件生成
- 从上周复制 / 从模板创建 / 跨日刷新编排

运行：python tests/smoke_m4.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from PySide6.QtCore import QTimer
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

from app import config
from app.database import init_db, set_setting
from app.models import experiment, record, weekly
from app.services import export_service
from app.ui import theme
from app.ui.main_window import MainWindow
from app.ui.pages.planner import PlannerPage
from app.ui.pages.weekly import WeeklyReviewPage
from app.utils import image_utils

# ---- 临时数据库隔离 ----
tmp = Path(tempfile.mkdtemp(prefix="lablog_m4_"))
config.DATA_DIR = tmp
config.DB_PATH = tmp / "lab.db"
config.IMAGES_DIR = tmp / "images"
config.FILES_DIR = tmp / "files"
config.BACKUPS_DIR = tmp / "backups"
config.EXPORTS_DIR = tmp / "exports"
config.SOUND_FILE = tmp / "reminder.wav"

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, bool(ok), detail))


def big_image() -> QImage:
    img = QImage(2000, 1500, QImage.Format_RGB32)
    img.fill(QColor(50, 120, 200))
    return img


def main() -> int:
    app = QApplication(sys.argv)
    init_db()

    # 固定用历史周（全在过去，统计可控）
    monday = "2026-09-07"
    sunday = "2026-09-13"

    # ---- 1. 周汇总统计 ----
    e_done = experiment.create({"title": "完成实验", "planned_start": f"{monday} 09:00", "duration_min": 60, "status": "done"})
    experiment.create({"title": "进行中", "planned_start": "2026-09-20 10:00", "duration_min": 60, "status": "running"})
    experiment.create({"title": "失败", "planned_start": f"{monday} 11:00", "duration_min": 60, "status": "failed"})
    experiment.create({"title": "超时", "planned_start": f"{monday} 08:00", "duration_min": 30, "status": "planned"})
    rec_id = record.create_record(e_done, "一条记录", f"{monday} 12:00:00")
    record.add_image(rec_id, e_done, image_utils.save_image(big_image()))

    stats = weekly.week_stats(monday, sunday)
    check("统计完成实验数", stats["done"] == 1, str(stats["done"]))
    check("统计进行中数", stats["running"] == 1, str(stats["running"]))
    check("统计失败数", stats["failed"] == 1, str(stats["failed"]))
    check("统计超时数", stats["overdue"] == 1, str(stats["overdue"]))
    check("统计记录数", stats["records"] == 1, str(stats["records"]))
    check("统计图片数", stats["images"] == 1, str(stats["images"]))

    # ---- 2. 规划项拖拽排序 ----
    d0 = f"{monday}"
    id1 = weekly.create_item({"week_start": monday, "title": "A", "planned_date": d0, "planned_start": "09:00", "duration_min": 60})
    id2 = weekly.create_item({"week_start": monday, "title": "B", "planned_date": d0, "planned_start": "10:00", "duration_min": 60})
    id3 = weekly.create_item({"week_start": monday, "title": "C", "planned_date": d0, "planned_start": "11:00", "duration_min": 60})
    # 拖拽：把 id3 提到最前
    weekly.reorder_date(d0, [id3, id1, id2])
    items = weekly.list_items_range(d0, d0)
    order = [it["id"] for it in items]
    check("拖拽后 sort_order 持久化", order == [id3, id1, id2], str(order))
    # 跨天：把 id2 移到另一天
    d1 = f"{sunday}"
    weekly.set_item_date_order(id2, d1, 0)
    check("跨天移动 planned_date", weekly.get_item(id2)["planned_date"] == d1)

    # ---- 3. 一键转实验 ----
    tmr = "2026-09-20"
    pid = weekly.create_item({"week_start": "2026-09-14", "title": "质粒构建", "type": "分子克隆",
                              "planned_date": tmr, "planned_start": "14:00", "duration_min": 180,
                              "priority": "high", "notes": "备注X"})
    exp_id = weekly.convert_to_experiment(pid)
    exp = experiment.get(exp_id)
    check("转实验创建 experiments 行", exp is not None and exp["title"] == "质粒构建")
    check("转实验开始时间", exp["planned_start"] == f"{tmr} 14:00", str(exp["planned_start"]))
    check("转实验结束时间", exp["planned_end"] == f"{tmr} 17:00", str(exp["planned_end"]))
    check("转实验耗时", exp["duration_min"] == 180)
    check("转实验自动武装提醒", exp["remind_enabled"] == 1 and exp["remind_on_time"] == 1)
    check("转实验来源标记", exp["source"] == "plan")
    item = weekly.get_item(pid)
    check("回写 linked_experiment_id", item["linked_experiment_id"] == exp_id)
    check("规划项状态转 converted", item["status"] == "converted")

    # ---- 4. 导出 Markdown / HTML ----
    review = weekly.get_or_create_review(monday)
    weekly.save_review_field(monday, "summary", "本周完成了质粒构建")
    review = weekly.get_review(monday)
    exps = weekly.week_experiments(monday, sunday)
    plan_items = weekly.list_items_range(monday, sunday)
    md = export_service.build_markdown(monday, review, stats, exps, plan_items, "测试周")
    check("导出 Markdown 内容", "本周总结" in md and "本周完成了质粒构建" in md)
    html = export_service.build_html(monday, review, stats, exps, plan_items, "测试周")
    check("导出 HTML 内容", html.startswith("<!DOCTYPE") and "实验周报" in html)
    md_path = config.EXPORTS_DIR / "test_week.md"
    md_path.write_text(md, encoding="utf-8")
    html_path = config.EXPORTS_DIR / "test_week.html"
    html_path.write_text(html, encoding="utf-8")
    check("导出文件落盘", md_path.exists() and html_path.exists())

    # ---- 5. 从上周复制 / 从模板 ----
    nxt = "2026-09-14"
    copied = weekly.copy_week(monday, nxt)
    check("从上周复制", len(copied) >= 1)
    tpl = weekly.create_from_template("2026-09-21")
    check("从模板创建", len(tpl) == 5, str(len(tpl)))

    # ---- 6. 跨日刷新编排（真实页面接入）----
    theme.apply(app, "light")
    win = MainWindow()
    win.show()
    check("周整理为真实页面", isinstance(win._pages["weekly"], WeeklyReviewPage))
    check("实验规划为真实页面", isinstance(win._pages["planner"], PlannerPage))
    set_setting("carry_over_enabled", True)
    win._on_day_changed("2026-09-16")
    check("跨日刷新编排无异常", True)

    QTimer.singleShot(300, app.quit)
    app.exec()

    failed = [r for r in results if not r[1]]
    for name, ok, detail in results:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))
    print(f"\n共 {len(results)} 项，通过 {len(results) - len(failed)}，失败 {len(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

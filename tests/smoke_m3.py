"""M3 冒烟测试（离屏运行，临时数据库隔离）：
- 图片压缩存储（最长边 1920，转 JPG，相对路径）
- Markdown 渲染（图片语法被剥离）
- 跨日结转（未完成实验平移到新日期）
- 记录时间线追加 / 图片关联 / 删除清理
- 每日记录 get_or_create 幂等 / 保存 / 追加
- 详情页时间线渲染、主窗口跨日刷新编排

运行：python tests/smoke_m3.py
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
from PySide6.QtGui import QColor, QImage, QImageReader
from PySide6.QtWidgets import QApplication

from app import config
from app.database import fetch_one, init_db, set_setting
from app.models import daily_log, experiment, record
from app.ui import theme
from app.ui.main_window import MainWindow
from app.ui.pages.experiment_detail import ExperimentDetailPage
from app.utils import image_utils, markdown_utils

# ---- 临时数据库隔离 ----
tmp = Path(tempfile.mkdtemp(prefix="lablog_m3_"))
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
    img = QImage(4000, 3000, QImage.Format_RGB32)
    img.fill(QColor(180, 90, 40))
    return img


def main() -> int:
    app = QApplication(sys.argv)
    init_db()

    # ---- 1. 图片压缩存储 ----
    rel = image_utils.save_image(big_image())
    saved = config.DATA_DIR / rel
    reader = QImageReader(str(saved))
    sz = reader.size()
    check("图片保存为相对路径 images/*.jpg", rel.startswith("images/") and rel.endswith(".jpg"), rel)
    check("图片文件已落盘", saved.exists(), str(saved))
    check("压缩后最长边≤1920", max(sz.width(), sz.height()) <= 1920, f"{sz.width()}x{sz.height()}")
    check("缩略图加载", image_utils.load_pixmap(rel, 200) is not None)

    # ---- 2. Markdown 渲染 ----
    html = markdown_utils.to_html("**加样**\n\n- 步骤一")
    check("Markdown 加粗", "<strong>加样</strong>" in html, html[:80])
    check("Markdown 列表", "<li>步骤一</li>" in html)
    check("图片语法被剥离", "<img" not in markdown_utils.to_html("文字 ![图](images/x.jpg) 后"))

    # ---- 3. 每日记录 ----
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    l1 = daily_log.get_or_create(today)
    l2 = daily_log.get_or_create(today)
    check("每日记录 get_or_create 幂等", l1["id"] == l2["id"])
    daily_log.save_content(today, "记录A")
    check("每日记录保存", daily_log.get_by_date(today)["content"] == "记录A")
    daily_log.append_content(today, "追加行")
    check("每日记录追加", "追加行" in daily_log.get_by_date(today)["content"])

    # ---- 4. 跨日结转 ----
    yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
    id_run = experiment.create({
        "title": "结转测试", "planned_start": f"{yesterday} 10:00",
        "duration_min": 120, "status": "running",
    })
    id_done = experiment.create({
        "title": "已完成", "planned_start": f"{yesterday} 09:00",
        "duration_min": 60, "status": "done",
    })
    notes = daily_log.carry_over_unfinished(yesterday, today)
    e_run = experiment.get(id_run)
    check("未完成实验日期平移", e_run["planned_start"].startswith(today), e_run["planned_start"])
    check("结转保留时间", e_run["planned_start"].endswith("10:00"))
    check("结转重算结束时间", e_run["planned_end"] == f"{today} 12:00", str(e_run["planned_end"]))
    check("已完成实验不结转", experiment.get(id_done)["planned_start"].startswith(yesterday))
    check("结转返回说明", len(notes) == 1, str(notes))

    # ---- 5. 记录时间线 ----
    rec_id = record.create_record(id_run, "**加样** 完成", f"{today} 10:05:00")
    check("记录追加", record.list_records(id_run)[0]["id"] == rec_id)
    img_rel = image_utils.save_image(big_image())
    record.add_image(rec_id, id_run, img_rel)
    imgs = record.list_images_for_record(rec_id)
    check("记录图片关联", len(imgs) == 1 and imgs[0]["path"] == img_rel)
    check("实验图片计数", record.count_images(id_run) == 1)
    record.delete_record(rec_id)
    check("删除记录", record.get(rec_id) is None)
    check("删除记录清理图片文件", not (config.DATA_DIR / img_rel).exists())

    # ---- 6. 详情页时间线渲染 ----
    rec_id2 = record.create_record(id_run, "第二条记录")
    record.add_image(rec_id2, id_run, image_utils.save_image(big_image()))
    detail = ExperimentDetailPage()
    detail.load(id_run)
    check("详情页标题加载", detail.title_label.text() == "结转测试")
    check("详情页时间线渲染", detail.timeline_layout.count() >= 2, str(detail.timeline_layout.count()))

    # ---- 7. 主窗口构建 + 跨日刷新编排 ----
    theme.apply(app, "light")
    win = MainWindow()
    win.show()
    check("主窗口构建", True)
    set_setting("carry_over_enabled", True)
    win._on_day_changed(today)  # 手动触发跨日刷新，不应抛异常
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

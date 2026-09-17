"""M2 冒烟测试（离屏运行，使用临时数据库，不污染真实数据）：
- experiments 数据访问层 CRUD
- 结束时间自动计算（含跨天：23:00 + 3h -> 次日 02:00）
- 提醒服务触发与去重（到点 5 分钟补提醒窗口、提前提醒）
- 主窗口构建（离屏环境无托盘）

运行：python tests/smoke_m2.py
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
from PySide6.QtWidgets import QApplication

from app import config
from app.database import fetch_one, init_db
from app.models import experiment
from app.services.reminder_service import ReminderService
from app.ui import theme
from app.ui.main_window import MainWindow
from app.utils import time_utils

# ---- 临时数据库隔离 ----
tmp = Path(tempfile.mkdtemp(prefix="lablog_m2_"))
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


def main() -> int:
    app = QApplication(sys.argv)
    init_db()

    # ---- 1. 结束时间计算（纯函数 + 模型）----
    check("同日 14:00+3h=17:00", time_utils.end_time_str("2026-09-16 14:00", 180) == "2026-09-16 17:00")
    check("跨天 23:00+3h=次日02:00", time_utils.end_time_str("2026-09-16 23:00", 180) == "2026-09-17 02:00")

    eid = experiment.create({
        "title": "合成质粒", "type": "分子克隆", "priority": "high",
        "planned_start": "2026-09-16 23:00", "duration_min": 180,
    })
    e = experiment.get(eid)
    check("创建实验", e is not None and e["title"] == "合成质粒")
    check("模型落库 planned_end 跨天", e["planned_end"] == "2026-09-17 02:00", str(e["planned_end"]))

    # ---- 2. 更新 + 删除 + 筛选 ----
    experiment.update(eid, {"title": "合成质粒V2", "planned_start": "2026-09-16 23:00", "duration_min": 180})
    e2 = experiment.get(eid)
    check("更新标题", e2["title"] == "合成质粒V2")
    check("更新后结束时间重算", e2["planned_end"] == "2026-09-17 02:00")

    experiment.create({"title": "跑胶", "status": "running", "planned_start": "2026-09-16 09:00", "duration_min": 60})
    check("按状态筛选", len(experiment.list_experiments(status="running")) == 1)
    check("关键词筛选", len(experiment.list_experiments(keyword="质粒")) == 1)

    experiment.delete(eid)
    check("删除实验", experiment.get(eid) is None)

    # ---- 3. 提醒服务：触发 + 去重 ----
    now = datetime.now()
    on_start = (now - timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M")     # 到点窗口内
    adv_start = (now + timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M")   # 提前 15 分钟应已到点
    future_start = (now + timedelta(minutes=60)).strftime("%Y-%m-%d %H:%M")

    id_on = experiment.create({"title": "到点提醒测试", "planned_start": on_start, "duration_min": 30,
                               "remind_enabled": 1, "remind_on_time": 1, "remind_advance_min": 0})
    id_adv = experiment.create({"title": "提前提醒测试", "planned_start": adv_start, "duration_min": 30,
                                "remind_enabled": 1, "remind_on_time": 0, "remind_advance_min": 15})
    id_future = experiment.create({"title": "未来实验", "planned_start": future_start, "duration_min": 30,
                                   "remind_enabled": 1, "remind_on_time": 1, "remind_advance_min": 0})

    svc = ReminderService()
    fired: list[dict] = []
    svc.fired.connect(fired.append)
    svc.check()

    check("到点提醒触发", any(e["kind"] == "on_time" and e["experiment_id"] == id_on for e in fired))
    check("提前提醒触发", any(e["kind"] == "advance" and e["experiment_id"] == id_adv for e in fired))
    check("未来实验不触发", not any(e["experiment_id"] == id_future for e in fired))

    svc.check()  # 再次扫描，应被 UNIQUE 去重
    check("重复扫描不再触发", len(fired) == 2, f"fired={len(fired)}")
    on_log = fetch_one(
        "SELECT COUNT(*) c FROM reminder_log WHERE experiment_id = ? AND remind_type = 'on_time'",
        (id_on,),
    )["c"]
    check("reminder_log 去重唯一", on_log == 1, f"count={on_log}")

    # ---- 4. 主窗口构建（离屏无托盘）----
    theme.apply(app, "light")
    win = MainWindow()
    win.show()
    check("主窗口构建", True)
    check("离屏环境托盘为 None", win.tray is None)

    QTimer.singleShot(500, app.quit)
    app.exec()

    failed = [r for r in results if not r[1]]
    for name, ok, detail in results:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))
    print(f"\n共 {len(results)} 项，通过 {len(results) - len(failed)}，失败 {len(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

"""M5 冒烟测试（离屏运行，临时数据库隔离）：
- 设置项读写
- 备份 / 恢复完整性（恢复后数据一致）
- 天气缓存逻辑（不联网）
- 无边框窗口 + 标题栏（构建、标志位、拖动方法、关闭）

运行：python tests/smoke_m5.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication

from app import config
from app.database import get_setting, init_db, set_setting
from app.models import experiment, record
from app.services import backup_service
from app.services.weather_service import WeatherService
from app.ui import theme
from app.ui.main_window import MainWindow
from app.ui.pages.settings_page import SettingsPage

# ---- 临时数据库隔离 ----
tmp = Path(tempfile.mkdtemp(prefix="lablog_m5_"))
config.DATA_DIR = tmp
config.DB_PATH = tmp / "lab.db"
config.IMAGES_DIR = tmp / "images"
config.FILES_DIR = tmp / "files"
config.BACKUPS_DIR = tmp / "backups"
config.EXPORTS_DIR = tmp / "exports"
config.SOUND_FILE = tmp / "reminder.wav"
config.WEATHER_CACHE = tmp / "weather_cache.json"

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, bool(ok), detail))


def main() -> int:
    app = QApplication(sys.argv)
    init_db()
    theme.apply(app, "light")

    # ---- 1. 设置项读写 ----
    set_setting("theme", "dark")
    check("设置读写 theme", get_setting("theme") == "dark")
    set_setting("remind_default_advance_min", 25)
    check("设置读写 remind", get_setting("remind_default_advance_min") == 25)
    set_setting("carry_over_enabled", True)
    check("设置读写结转开关", get_setting("carry_over_enabled") is True)
    set_setting("weather_city", "上海")
    check("设置读写天气城市", get_setting("weather_city") == "上海")

    # ---- 2. 备份 / 恢复完整性 ----
    eid = experiment.create({"title": "备份测试实验", "planned_start": "2026-09-16 10:00",
                             "duration_min": 60, "status": "done"})
    record.create_record(eid, "一条记录")
    zip_path = backup_service.backup()
    check("备份生成", zip_path.exists(), str(zip_path))
    check("备份校验可恢复", backup_service.validate_backup(zip_path))
    experiment.delete(eid)
    check("删除后实验消失", experiment.get(eid) is None)
    backup_service.restore(zip_path)
    restored = experiment.get(eid)
    check("恢复后实验回来", restored is not None and restored["title"] == "备份测试实验")
    recs = record.list_records(eid)
    check("恢复后记录一致", len(recs) == 1)

    # ---- 3. 天气缓存逻辑 ----
    ws = WeatherService()
    check("初始无缓存", ws.load_cache() is None)
    ws._save_cache({"temp": 26, "text": "晴", "icon": "sun", "city": "北京",
                    "updated_at": "2026-09-16 18:00", "provider": "wttr"})
    cached = ws.load_cache()
    check("缓存写入可读", cached is not None and cached["temp"] == 26)
    # 失败回退到缓存
    fired: list = []
    ws.ready.connect(lambda d: fired.append(("ready", d)))
    ws.failed.connect(lambda e: fired.append(("failed", e)))
    ws._on_done(None, "所有天气源均获取失败")
    check("失败时回退缓存", any(k == "ready" and d.get("from_cache") for k, d in fired))

    # ---- 4. 无边框窗口 + 标题栏 ----
    win = MainWindow()
    win.show()
    check("无边框标志", bool(win.windowFlags() & Qt.FramelessWindowHint))
    check("标题栏存在", hasattr(win, "titlebar"))
    check("标题栏拖动方法", callable(getattr(win.titlebar, "mouseMoveEvent", None)))
    check("窗口按钮存在", win.titlebar.min_btn is not None and win.titlebar.close_btn is not None)
    check("设置页为真实页", isinstance(win._pages["settings"], SettingsPage))
    win.close()  # 离屏无托盘 → 直接关闭
    check("窗口关闭无异常", True)

    QTimer.singleShot(200, app.quit)
    app.exec()

    failed = [r for r in results if not r[1]]
    for name, ok, detail in results:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))
    print(f"\n共 {len(results)} 项，通过 {len(results) - len(failed)}，失败 {len(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

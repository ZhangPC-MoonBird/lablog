"""M1 冒烟测试（离屏运行，不弹窗口）：
- 数据库初始化、11 张表创建、默认设置写入
- 主窗口构建、时钟 HH:MM:SS 每秒刷新、日期中文格式
- 亮/暗主题切换、五个页面切换

运行：python tests/smoke_m1.py
"""
from __future__ import annotations

import os
import re
import sys
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
from app.database import fetch_all, init_db
from app.ui import theme
from app.ui.main_window import MainWindow

EXPECTED_TABLES = {
    "app_meta", "settings", "experiments", "reminder_log",
    "experiment_records", "record_images", "attachments",
    "daily_logs", "weekly_reviews", "weekly_plans", "plan_items",
}

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, bool(ok), detail))


def main() -> int:
    app = QApplication(sys.argv)

    # 1. 数据库
    init_db()
    tables = {r["name"] for r in fetch_all("SELECT name FROM sqlite_master WHERE type='table'")}
    check("数据库文件创建", config.DB_PATH.exists(), str(config.DB_PATH))
    check("11 张数据表创建", EXPECTED_TABLES <= tables, f"缺少: {EXPECTED_TABLES - tables}")
    check("默认设置写入", bool(fetch_all("SELECT key FROM settings")), "")

    # 2. 主窗口 + 时钟
    theme.apply(app, "light")
    win = MainWindow()
    win.show()

    t0 = win.clock_label.text()
    check("时钟显示 HH:MM:SS", re.fullmatch(r"\d{2}:\d{2}:\d{2}", t0) is not None, t0)
    check(
        "日期中文格式",
        "年" in win.date_label.text() and "星期" in win.date_label.text(),
        win.date_label.text(),
    )

    def after_tick():
        t1 = win.clock_label.text()
        check("时钟每秒刷新", t1 != t0, f"{t0} -> {t1}")

        # 3. 主题切换
        win.toggle_theme()
        check("切到暗色主题", theme.current()["name"] == "dark", theme.current()["name"])
        win.toggle_theme()
        check("切回亮色主题", theme.current()["name"] == "light", theme.current()["name"])

        # 4. 五个页面切换
        for key in ("experiments", "planner", "weekly", "settings", "dashboard"):
            win.switch_page(key)
        check("五个页面切换无异常", True, "")

        app.quit()

    QTimer.singleShot(1500, after_tick)
    app.exec()

    failed = [r for r in results if not r[1]]
    for name, ok, detail in results:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))
    print(f"\n共 {len(results)} 项，通过 {len(results) - len(failed)}，失败 {len(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

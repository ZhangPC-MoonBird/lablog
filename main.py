"""实验助手 —— 本地实验计划与记录助手。程序入口。

运行：python main.py（或双击 启动LabLog.vbs）
启动日志写入 data/startup.log，便于诊断 pythonw / 双击等无控制台场景。
"""
from __future__ import annotations

import logging
import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox

from app import config
from app.database import get_setting, init_db
from app.ui import theme
from app.ui.main_window import MainWindow


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:  # 控制台重定向失败不影响启动
        pass

    # 启动日志：写到 data/startup.log，方便定位“双击无反应”等无控制台问题
    try:
        config.ensure_dirs()
        logging.basicConfig(
            filename=str(config.DATA_DIR / "startup.log"),
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
            encoding="utf-8",
        )
    except Exception:
        logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    logging.info("=== 实验助手 v%s 启动 ===", config.APP_VERSION)
    try:
        return _run()
    except Exception:
        logging.exception("启动失败")
        try:
            QMessageBox.critical(None, config.APP_NAME, "程序启动失败，详见 data/startup.log")
        except Exception:
            pass
        return 1


def _run() -> int:
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setApplicationName(config.APP_NAME)
    app.setOrganizationName(config.ORG_NAME)

    try:
        init_db()
    except Exception:
        logging.exception("数据库初始化失败")
        QMessageBox.critical(None, config.APP_NAME, "本地数据库初始化失败，请检查 data 目录权限。")
        return 1

    theme.apply(app, get_setting("theme", "light"))

    win = MainWindow()
    win.show()
    logging.info("主窗口已显示")
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())

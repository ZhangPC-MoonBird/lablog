"""应用配置：名称、版本、路径常量与目录初始化。"""
from __future__ import annotations

import sys
from pathlib import Path

APP_NAME = "实验助手"
APP_VERSION = "0.1.0"
ORG_NAME = "LabLog"


def is_frozen() -> bool:
    """是否运行在 PyInstaller 打包环境中。"""
    return getattr(sys, "frozen", False)


def base_dir() -> Path:
    """项目根目录。打包后资源在临时解包目录 _MEIPASS 内。"""
    if is_frozen():
        return Path(sys._MEIPASS)  # noqa: SLF001
    return Path(__file__).resolve().parent.parent


BASE_DIR = base_dir()

# 数据目录：始终放在可写位置（打包后放在 exe 同级，避免写进临时目录）
if is_frozen():
    DATA_DIR = Path(sys.executable).resolve().parent / "data"
else:
    DATA_DIR = BASE_DIR / "data"

DB_PATH = DATA_DIR / "lab.db"
IMAGES_DIR = DATA_DIR / "images"
FILES_DIR = DATA_DIR / "files"
BACKUPS_DIR = DATA_DIR / "backups"
EXPORTS_DIR = DATA_DIR / "exports"
WEATHER_CACHE = DATA_DIR / "weather_cache.json"

ASSETS_DIR = BASE_DIR / "assets"
ICONS_DIR = ASSETS_DIR / "icons"
ILLUSTRATIONS_DIR = ASSETS_DIR / "illustrations"
WEATHER_ICONS_DIR = ASSETS_DIR / "weather"
THEMES_DIR = ASSETS_DIR / "themes"
FONTS_DIR = ASSETS_DIR / "fonts"
SOUNDS_DIR = ASSETS_DIR / "sounds"
SOUND_FILE = DATA_DIR / "reminder.wav"  # 程序生成的提示音（wave 模块，无版权问题）


def ensure_dirs() -> None:
    """确保所有运行时目录存在（数据不丢失的前提）。"""
    for d in (DATA_DIR, IMAGES_DIR, FILES_DIR, BACKUPS_DIR, EXPORTS_DIR):
        d.mkdir(parents=True, exist_ok=True)

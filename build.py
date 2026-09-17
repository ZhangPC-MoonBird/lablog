"""安全打包脚本（重要：以后打包都用它，不要手动 rm -rf dist）。

流程：打包前先把 dist/实验助手/data/ 备份到临时目录 → 清理重新打包 → 把 data 移回。
这样每次重新打包 exe，用户的数据（数据库/图片/附件）都不会被清空。

用法：python build.py
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DIST_DIR = ROOT / "dist" / "实验助手"
DATA_DIR = DIST_DIR / "data"
BACKUP_DIR = ROOT / ".data_backup_tmp"
SPEC = ROOT / "实验助手.spec"


def main() -> int:
    # 1. 打包前备份 dist 里的 data（若存在）
    backed_up = False
    if DATA_DIR.exists():
        if BACKUP_DIR.exists():
            shutil.rmtree(BACKUP_DIR)
        shutil.move(str(DATA_DIR), str(BACKUP_DIR))
        backed_up = True
        print(f"[打包] 已备份数据 -> {BACKUP_DIR}")

    try:
        # 2. 清理旧的打包产物（data 已被备份，安全）
        for d in (ROOT / "build", DIST_DIR):
            if d.exists():
                shutil.rmtree(d)
        if SPEC.exists():
            SPEC.unlink()

        # 3. 重新打包
        cmd = [
            sys.executable, "-m", "PyInstaller",
            "--noconsole", "--name", "实验助手",
            "--icon", "assets/app_icon.ico",
            "--add-data", "assets;assets",
            "--collect-all", "markdown",
            "--collect-all", "docx",
            "--collect-all", "PySide6.QtMultimedia",
            "--exclude-module", "PySide6.QtWebEngineCore",
            "--exclude-module", "PySide6.QtWebEngineWidgets",
            "main.py",
        ]
        print("[打包] 开始 PyInstaller 打包…")
        subprocess.run(cmd, cwd=str(ROOT), check=True)
    finally:
        # 4. 打包结束（无论成败）恢复 data
        if backed_up and BACKUP_DIR.exists():
            if DATA_DIR.exists():
                shutil.rmtree(DATA_DIR)
            shutil.move(str(BACKUP_DIR), str(DATA_DIR))
            print(f"[打包] 已恢复数据 -> {DATA_DIR}")

    print("[打包] 完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())

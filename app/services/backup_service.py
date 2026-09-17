"""备份与恢复。

- 备份：lab.db + images/ + files/ 打包成 zip 到 data/backups/
- 恢复：先校验 zip 内 lab.db 可打开，再解压覆盖，返回后由调用方提示重启

关键：恢复前必须先确认数据库可打开（用临时副本校验），避免损坏数据。
本应用的 SQLite 采用短连接（每次操作独立连接），因此恢复时无需显式关闭连接，
但校验副本可打开是必要的安全检查。
"""
from __future__ import annotations

import shutil
import sqlite3
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

from .. import config


def backup(dest_path: Path | None = None) -> Path:
    """备份数据，返回生成的 zip 路径。

    dest_path：指定的 zip 完整路径（用户手动备份时选的目标）；
    None 时用默认 data/backups/backup_时间戳.zip（自动备份用）。
    """
    if dest_path is None:
        config.BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
        iso = datetime.now().isocalendar()
        # 按周命名：同一周内多次备份覆盖同一文件，不同周分开
        dest_path = config.BACKUPS_DIR / f"backup_{iso[0]}_W{iso[1]:02d}.zip"
    else:
        dest_path = Path(dest_path)
        dest_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dest_path, "w", zipfile.ZIP_DEFLATED) as zf:
        if config.DB_PATH.exists():
            zf.write(config.DB_PATH, "lab.db")
        for d, prefix in ((config.IMAGES_DIR, "images"), (config.FILES_DIR, "files")):
            if d.exists():
                for f in d.rglob("*"):
                    if f.is_file():
                        zf.write(f, f"{prefix}/{f.name}")
    return dest_path


def list_backups() -> list[Path]:
    """按时间倒序返回已有备份。"""
    if not config.BACKUPS_DIR.exists():
        return []
    return sorted(config.BACKUPS_DIR.glob("*.zip"), reverse=True)


def validate_backup(zip_path: Path) -> bool:
    """校验备份内 lab.db 可打开（不解压覆盖，用临时副本）。"""
    try:
        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
            if "lab.db" not in names:
                return False
            with tempfile.TemporaryDirectory() as tmp:
                tmp_db = Path(tmp) / "lab.db"
                with zf.open("lab.db") as src, open(tmp_db, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                conn = sqlite3.connect(str(tmp_db))
                try:
                    conn.execute("SELECT name FROM sqlite_master LIMIT 1").fetchall()
                finally:
                    conn.close()
        return True
    except Exception:
        return False


def restore(zip_path: Path) -> None:
    """解压覆盖 data/。调用前应先 validate_backup。"""
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(config.DATA_DIR)
    # 清理 WAL / SHM 残留，确保恢复后的库被干净读取
    for suffix in ("-wal", "-shm"):
        p = Path(str(config.DB_PATH) + suffix)
        if p.exists():
            p.unlink()

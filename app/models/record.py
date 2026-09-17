"""实验记录数据访问层（experiment_records + record_images）。

图片文件存 data/images/，这里只存相对路径（images/xxx.jpg）。
删除记录时同步删除关联的图片文件。
"""
from __future__ import annotations

from ..database import execute, fetch_all, fetch_one, now_str
from ..utils import image_utils


def create_record(experiment_id: int, content: str = "", record_time: str | None = None) -> int:
    """新增一条记录，返回记录 id。record_time 默认当前时间（可手动指定）。"""
    return execute(
        "INSERT INTO experiment_records(experiment_id, record_time, content) VALUES(?, ?, ?)",
        (experiment_id, record_time or now_str(), content or ""),
    )


def get(record_id: int) -> dict | None:
    return fetch_one("SELECT * FROM experiment_records WHERE id = ?", (record_id,))


def update_record(record_id: int, content: str, record_time: str) -> None:
    execute(
        "UPDATE experiment_records SET content = ?, record_time = ?, updated_at = ? WHERE id = ?",
        (content, record_time, now_str(), record_id),
    )


def delete_record(record_id: int) -> None:
    """删除记录并清理其图片文件（record_images 经外键级联删除）。"""
    for img in list_images_for_record(record_id):
        image_utils.delete_image(img["path"])
    execute("DELETE FROM experiment_records WHERE id = ?", (record_id,))


def list_records(experiment_id: int) -> list[dict]:
    """按时间倒序（最新在上）返回某实验的全部记录。"""
    return fetch_all(
        "SELECT * FROM experiment_records WHERE experiment_id = ? ORDER BY record_time DESC, id DESC",
        (experiment_id,),
    )


def add_image(record_id: int, experiment_id: int, relative_path: str) -> int:
    return execute(
        "INSERT INTO record_images(record_id, experiment_id, path) VALUES(?, ?, ?)",
        (record_id, experiment_id, relative_path),
    )


def list_images_for_record(record_id: int) -> list[dict]:
    return fetch_all("SELECT * FROM record_images WHERE record_id = ? ORDER BY id", (record_id,))


def list_images(experiment_id: int) -> list[dict]:
    """某实验的全部图片（用于统计）。"""
    return fetch_all(
        "SELECT * FROM record_images WHERE experiment_id = ? ORDER BY id", (experiment_id,)
    )


def count_images(experiment_id: int) -> int:
    row = fetch_one(
        "SELECT COUNT(*) c FROM record_images WHERE experiment_id = ?", (experiment_id,)
    )
    return row["c"] if row else 0


# ---------------------------------------------------------------------------
# 实验结论图片（复用 record_images 表，record_id 为 NULL 表示结论图片）
# ---------------------------------------------------------------------------
def add_conclusion_image(experiment_id: int, relative_path: str) -> int:
    return execute(
        "INSERT INTO record_images(record_id, experiment_id, path) VALUES(NULL, ?, ?)",
        (experiment_id, relative_path),
    )


def list_conclusion_images(experiment_id: int) -> list[dict]:
    return fetch_all(
        "SELECT * FROM record_images WHERE experiment_id = ? AND record_id IS NULL ORDER BY id",
        (experiment_id,),
    )


def delete_conclusion_image(image_id: int) -> None:
    img = fetch_one("SELECT * FROM record_images WHERE id = ?", (image_id,))
    if img:
        image_utils.delete_image(img["path"])
    execute("DELETE FROM record_images WHERE id = ?", (image_id,))

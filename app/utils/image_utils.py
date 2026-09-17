"""图片处理：压缩、保存、加载缩略图、删除。

所有图片统一压缩为 JPG（最长边默认 1920px）存入 data/images/，
数据库只存相对路径（images/xxx.jpg），防止大图（尤其粘贴截图）撑爆内存 / 拖慢 UI。
"""
from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QImage, QImageReader, QPixmap

from .. import config

MAX_EDGE = 1920
JPEG_QUALITY = 85


def compress_image(image: QImage, max_edge: int = MAX_EDGE) -> QImage:
    """按最长边等比缩放（不放大）。"""
    if image.isNull():
        return image
    w, h = image.width(), image.height()
    longest = max(w, h)
    if longest > max_edge:
        scale = max_edge / longest
        image = image.scaled(
            max(1, int(w * scale)), max(1, int(h * scale)),
            Qt.KeepAspectRatio, Qt.SmoothTransformation,
        )
    return image


def save_image(image: QImage, max_edge: int = MAX_EDGE, quality: int = JPEG_QUALITY) -> str:
    """压缩并保存图片，返回相对路径 'images/xxx.jpg'。"""
    image = compress_image(image, max_edge)
    config.IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}.jpg"
    path = config.IMAGES_DIR / filename
    image.save(str(path), "JPG", quality)
    return f"images/{filename}"


def save_image_file(src: str | Path, max_edge: int = MAX_EDGE, quality: int = JPEG_QUALITY) -> str | None:
    """从文件路径加载并压缩保存；失败返回 None。"""
    img = QImage(str(src))
    if img.isNull():
        return None
    return save_image(img, max_edge, quality)


def delete_image(relative_path: str) -> None:
    """删除某张图片文件（best-effort）。"""
    try:
        absolute_path(relative_path).unlink(missing_ok=True)
    except OSError:
        pass


def absolute_path(relative_path: str) -> Path:
    return config.DATA_DIR / relative_path


def load_pixmap(relative_path: str, max_edge: int = 0) -> QPixmap | None:
    """加载图片为 QPixmap；max_edge > 0 时按最长边缩放（用 QImageReader 降低内存占用）。"""
    p = absolute_path(relative_path)
    if not p.exists():
        return None
    reader = QImageReader(str(p))
    reader.setAutoTransform(True)
    if max_edge > 0:
        s = reader.size()
        if s.isValid() and max(s.width(), s.height()) > max_edge:
            scale = max_edge / max(s.width(), s.height())
            reader.setScaledSize(QSize(max(1, int(s.width() * scale)), max(1, int(s.height() * scale))))
    img = reader.read()
    if img.isNull():
        return None
    return QPixmap.fromImage(img)

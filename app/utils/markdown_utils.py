"""Markdown 渲染。

记录正文渲染为 HTML 后交给 QLabel（富文本）显示。
图片语法在渲染前被移除——时间线里的图片以独立缩略图展示，不内联进正文，
避免大量图片塞进同一文本控件导致卡顿。
"""
from __future__ import annotations

import re

import markdown

_IMG_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)")


def strip_images(text: str) -> str:
    """移除 Markdown 图片语法。"""
    return _IMG_RE.sub("", text or "")


def to_html(text: str) -> str:
    """Markdown -> HTML（用于只读展示）。"""
    return markdown.markdown(
        strip_images(text),
        extensions=["fenced_code", "tables", "sane_lists"],
    )

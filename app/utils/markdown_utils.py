"""Markdown 渲染。

记录正文渲染为 HTML 后交给 QLabel（富文本）显示。
正文中的图片链接（images/xxx.jpg）会转换为带绝对 file:// 路径的 <img>，
让插入的图片直接显示在记录正文里。
"""
from __future__ import annotations

import re

import markdown

from . import image_utils

_IMG_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)")


def strip_images(text: str) -> str:
    """移除 Markdown 图片语法。"""
    return _IMG_RE.sub("", text or "")


_IMG_WITH_PATH_RE = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")


def _embed_images(text: str) -> str:
    """把本地图片链接（images/…）替换为可显示的 HTML <img>；其余原样保留。"""
    def repl(match: re.Match) -> str:
        path = match.group(1).strip()
        if path.startswith("images/"):
            return image_utils.inline_image_html(path)
        return match.group(0)

    return _IMG_WITH_PATH_RE.sub(repl, text or "")


def to_html(text: str) -> str:
    """Markdown -> HTML（用于只读展示）。"""
    return markdown.markdown(
        _embed_images(text),
        extensions=["fenced_code", "tables", "sane_lists"],
    )

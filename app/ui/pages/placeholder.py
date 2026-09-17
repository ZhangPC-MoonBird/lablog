"""占位页面：里程碑未实现模块的展示页。"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ..components import Card, IconCircle


class PlaceholderPage(QWidget):
    def __init__(self, title: str, milestone: str, desc: str, icon_name: str = "calendar", parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 24, 28, 24)
        outer.addStretch(2)

        card = Card()
        card.setFixedWidth(460)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(36, 40, 36, 40)
        lay.setSpacing(12)
        lay.setAlignment(Qt.AlignHCenter)

        self._circle = IconCircle(icon_name, 26)
        lay.addWidget(self._circle, 0, Qt.AlignHCenter)

        t = QLabel(title)
        t.setObjectName("pageTitle")
        t.setAlignment(Qt.AlignCenter)
        lay.addWidget(t)

        chip = QLabel(f"M{milestone} 里程碑实现")
        chip.setObjectName("chip")
        lay.addWidget(chip, 0, Qt.AlignHCenter)

        d = QLabel(desc)
        d.setObjectName("muted")
        d.setWordWrap(True)
        d.setAlignment(Qt.AlignCenter)
        lay.addWidget(d)

        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(card)
        row.addStretch()
        outer.addLayout(row)
        outer.addStretch(3)

    def on_theme_changed(self) -> None:
        """主题切换后重绘图标颜色。"""
        self._circle.refresh_color()

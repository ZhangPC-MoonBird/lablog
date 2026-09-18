"""主题：配色常量、QSS 生成与全局应用。

需求规定的配色：
- 亮色：主色 #4F8CFF，背景 #F7F9FC
- 暗色：背景 #111827，卡片 #1F2937

主题一致性策略：所有控件的颜色统一由 QSS 控制（QPalette 仅作兜底），
覆盖表格/输入框/下拉/按钮/菜单/滚动区等标准控件，避免“表格深、外面白”的不一致。
"""
from __future__ import annotations

from PySide6.QtGui import QColor, QPalette

LIGHT = {
    "name": "light",
    "bg": "#F7F9FC",
    "card": "#FFFFFF",
    "sidebar_bg": "#FFFFFF",
    "primary": "#4F8CFF",
    "primary_hover": "#6FA3FF",
    "primary_tint": "#EAF2FF",
    "text": "#1F2937",
    "subtext": "#6B7280",
    "border": "#E5EAF2",
    "hover": "#EEF2F8",
    "danger": "#EF4444",
    "success": "#10B981",
    "warning": "#F59E0B",
    "shadow": (15, 23, 42, 24),
}

DARK = {
    "name": "dark",
    "bg": "#111827",
    "card": "#1F2937",
    "sidebar_bg": "#1F2937",
    "primary": "#4F8CFF",
    "primary_hover": "#6FA3FF",
    "primary_tint": "#24344D",
    "text": "#F3F4F6",
    "subtext": "#9CA3AF",
    "border": "#374151",
    "hover": "#263244",
    "danger": "#F87171",
    "success": "#34D399",
    "warning": "#FBBF24",
    "shadow": (0, 0, 0, 90),
}

COLORS = {"light": LIGHT, "dark": DARK}
_CURRENT = "light"


def current() -> dict:
    """当前主题配色字典。"""
    return COLORS[_CURRENT]


def apply(app, name: str = "light") -> None:
    """切换全局主题：QSS 为主，QPalette 兜底。"""
    global _CURRENT
    _CURRENT = name if name in COLORS else "light"
    c = COLORS[_CURRENT]
    app.setStyleSheet(build_qss(c))

    pal = QPalette()
    for role, color in (
        (QPalette.Window, QColor(c["bg"])),
        (QPalette.Base, QColor(c["card"])),
        (QPalette.AlternateBase, QColor(c["hover"])),
        (QPalette.Text, QColor(c["text"])),
        (QPalette.WindowText, QColor(c["text"])),
        (QPalette.Button, QColor(c["card"])),
        (QPalette.ButtonText, QColor(c["text"])),
        (QPalette.BrightText, QColor("#FFFFFF")),
        (QPalette.Highlight, QColor(c["primary"])),
        (QPalette.HighlightedText, QColor("#FFFFFF")),
        (QPalette.PlaceholderText, QColor(c["subtext"])),
        (QPalette.ToolTipBase, QColor(c["card"])),
        (QPalette.ToolTipText, QColor(c["text"])),
        (QPalette.Link, QColor(c["primary"])),
    ):
        pal.setColor(role, color)
    pal.setColor(QPalette.Disabled, QPalette.Text, QColor(c["subtext"]))
    pal.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(c["subtext"]))
    app.setPalette(pal)


# QSS 模板：__XXX__ 占位符替换为主题色
_QSS = """
* { font-family: "Microsoft YaHei UI", "PingFang SC", "Segoe UI", "Noto Sans CJK SC", sans-serif; }

/* 全局：背景与文字色（QFrame 子类会绘制；普通 QWidget 需 WA_StyledBackground） */
QWidget { background: __BG__; color: __TEXT__; font-size: 14px; }
QLabel { background: transparent; }
QMainWindow, QWidget#appRoot { background: __BG__; }

/* 左侧导航栏 */
QFrame#sidebar { background: __SIDEBAR_BG__; border-right: 1px solid __BORDER__; }
QLabel#appName { font-size: 17px; font-weight: 600; color: __TEXT__; background: transparent; }
QPushButton#navBtn {
    background: transparent; border: none; border-radius: 8px;
    padding: 9px 12px; text-align: left; color: __SUBTEXT__; font-size: 14px;
}
QPushButton#navBtn:hover { background: __HOVER__; color: __TEXT__; }
QPushButton#navBtn:checked { background: __PRIMARY_TINT__; color: __PRIMARY__; font-weight: 600; }

/* 顶部状态栏 / 自绘标题栏 */
QFrame#topBar { background: __CARD__; border: none; border-bottom: 1px solid __BORDER__; }
QFrame#titleBar { background: __CARD__; border: none; border-bottom: 1px solid __BORDER__; }
QPushButton#closeBtn { background: transparent; border: none; border-radius: 6px; }
QPushButton#closeBtn:hover { background: __DANGER__; }
QLabel#dateLabel { color: __SUBTEXT__; font-size: 14px; background: transparent; }
QLabel#clockLabel { color: __TEXT__; font-size: 22px; font-weight: 700; background: transparent; }
QWidget#weatherChip { background: __BG__; border: 1px solid __BORDER__; border-radius: 14px; }

/* 卡片 */
QFrame#card { background: __CARD__; border: 1px solid __BORDER__; border-radius: 12px; }
QWidget#card { background: __CARD__; border: 1px solid __BORDER__; border-radius: 12px; }
QLabel#pageTitle { font-size: 20px; font-weight: 700; color: __TEXT__; background: transparent; }
QLabel#cardTitle { font-size: 15px; font-weight: 600; color: __TEXT__; background: transparent; }
QLabel#statValue { font-size: 26px; font-weight: 700; color: __TEXT__; background: transparent; }
QLabel#muted { color: __SUBTEXT__; background: transparent; font-size: 13px; }
QLabel#chip { background: __PRIMARY_TINT__; color: __PRIMARY__; border-radius: 10px;
              padding: 3px 10px; font-size: 12px; }

/* 输入控件 */
QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox, QComboBox,
QDateEdit, QTimeEdit, QDateTimeEdit {
    background: __CARD__; color: __TEXT__;
    border: 1px solid __BORDER__; border-radius: 6px; padding: 3px 8px;
    selection-background-color: __PRIMARY__; selection-color: #FFFFFF;
}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QSpinBox:focus,
QComboBox:focus, QDateEdit:focus, QTimeEdit:focus, QDateTimeEdit:focus {
    border: 1px solid __PRIMARY__;
}
QPlainTextEdit, QTextEdit { padding: 6px 8px; }
QComboBox::drop-down { border: none; width: 22px; }
QComboBox::down-arrow {
    width: 0; height: 0;
    border-left: 4px solid transparent; border-right: 4px solid transparent;
    border-top: 5px solid __SUBTEXT__; margin-right: 8px;
}
QComboBox QAbstractItemView {
    background: __CARD__; color: __TEXT__; border: 1px solid __BORDER__;
    selection-background-color: __PRIMARY_TINT__; selection-color: __TEXT__;
    outline: 0;
}
QSpinBox::up-button, QSpinBox::down-button,
QDateEdit::up-button, QDateEdit::down-button,
QTimeEdit::up-button, QTimeEdit::down-button {
    background: transparent; border: none; width: 16px;
}
QSpinBox::up-arrow, QDateEdit::up-arrow, QTimeEdit::up-arrow {
    width: 0; height: 0; border-left: 4px solid transparent;
    border-right: 4px solid transparent; border-bottom: 5px solid __SUBTEXT__;
}
QSpinBox::down-arrow, QDateEdit::down-arrow, QTimeEdit::down-arrow {
    width: 0; height: 0; border-left: 4px solid transparent;
    border-right: 4px solid transparent; border-top: 5px solid __SUBTEXT__;
}

/* 按钮 */
QPushButton {
    background: __CARD__; color: __TEXT__;
    border: 1px solid __BORDER__; border-radius: 6px; padding: 5px 12px;
}
QPushButton:hover { border-color: __PRIMARY__; color: __PRIMARY__; }
QPushButton:pressed { background: __HOVER__; }
QPushButton:disabled { color: __SUBTEXT__; }
QPushButton:default { border-color: __PRIMARY__; }
QPushButton#primaryBtn {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 __PRIMARY__, stop:1 __PRIMARY_HOVER__);
    color: #FFFFFF; border: none; border-radius: 6px; padding: 6px 14px; font-weight: 600;
}
QPushButton#primaryBtn:hover { background: __PRIMARY_HOVER__; }
QPushButton#primaryBtn:pressed { background: __PRIMARY__; }
QPushButton#iconBtn { background: transparent; border: none; border-radius: 8px; padding: 6px; }
QPushButton#iconBtn:hover { background: __HOVER__; }
QPushButton#expTitleBtn {
    background: transparent; border: none; text-align: left;
    padding: 0; font-weight: 600; color: __TEXT__; font-size: 14px;
}
QPushButton#expTitleBtn:hover { color: __PRIMARY__; }

/* 表格 */
QTableView, QTableWidget {
    background: __CARD__; color: __TEXT__;
    gridline-color: __BORDER__; border: 1px solid __BORDER__; border-radius: 8px;
    alternate-background-color: __HOVER__;
    selection-background-color: __PRIMARY_TINT__; selection-color: __TEXT__;
}
QTableView::item:selected, QTableWidget::item:selected {
    background: __PRIMARY_TINT__; color: __TEXT__;
}
QHeaderView::section {
    background: __HOVER__; color: __SUBTEXT__; border: none;
    border-bottom: 1px solid __BORDER__; padding: 6px 8px;
}
QTableCornerButton::section { background: __HOVER__; border: none; }

/* 列表：选中整行浅色填充 */
QListWidget, QListWidget::item { background: __CARD__; color: __TEXT__; }
QListWidget { border: 1px solid __BORDER__; border-radius: 6px; }
QListWidget::item { padding: 7px 10px; border-bottom: 1px solid __BORDER__; }
QListWidget::item:selected { background: __PRIMARY_TINT__; color: __TEXT__; }
QListWidget::item:hover { background: __HOVER__; }

/* 滚动区域 */
QScrollArea { background: transparent; border: none; }
QScrollArea > QWidget > QWidget { background: transparent; }
QScrollBar:vertical { background: transparent; width: 8px; margin: 2px; }
QScrollBar::handle:vertical { background: __BORDER__; border-radius: 4px; min-height: 32px; }
QScrollBar::handle:vertical:hover { background: __SUBTEXT__; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal { background: transparent; height: 8px; margin: 2px; }
QScrollBar::handle:horizontal { background: __BORDER__; border-radius: 4px; min-width: 32px; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }

/* 菜单 */
QMenu { background: __CARD__; color: __TEXT__; border: 1px solid __BORDER__; }
QMenu::item { padding: 5px 24px; }
QMenu::item:selected { background: __PRIMARY_TINT__; }
QMenu::separator { height: 1px; background: __BORDER__; margin: 4px 0; }

/* 对话框 / 复选框 */
QDialog { background: __BG__; }
QMessageBox { background: __BG__; }
QCheckBox, QRadioButton { background: transparent; color: __TEXT__; spacing: 6px; }
QCheckBox::indicator {
    width: 16px; height: 16px;
    border: 2px solid __SUBTEXT__; border-radius: 4px; background: transparent;
}
QCheckBox::indicator:hover { border-color: __PRIMARY__; }
QCheckBox::indicator:checked { background: __PRIMARY__; border-color: __PRIMARY__; }
QRadioButton::indicator {
    width: 16px; height: 16px;
    border: 2px solid __SUBTEXT__; border-radius: 8px; background: transparent;
}
QRadioButton::indicator:hover { border-color: __PRIMARY__; }
QRadioButton::indicator:checked { background: __PRIMARY__; border-color: __PRIMARY__; }

QToolTip { background: __CARD__; color: __TEXT__; border: 1px solid __BORDER__; padding: 4px 8px; }
"""


def build_qss(c: dict) -> str:
    s = _QSS
    for key, value in c.items():
        if isinstance(value, str):
            s = s.replace(f"__{key.upper()}__", value)
    return s

"""通用 UI 组件：卡片、图标加载与渲染、状态徽章、提醒弹窗。

图标方案：assets/icons 下的本地 SVG（stroke 风格、以 currentColor 占位），
按主题颜色实时着色渲染，避免为亮/暗两套主题重复制作图标文件。
"""
from __future__ import annotations

import re

from PySide6.QtCore import QByteArray, QEasingCurve, QMimeData, QPoint, QPropertyAnimation, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QGuiApplication, QIcon, QImage, QKeySequence, QPainter, QPixmap, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QColorDialog,
    QDialog,
    QFileDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QLayout,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

try:
    from PySide6.QtSvg import QSvgRenderer
    _HAS_SVG_RENDERER = True
except ImportError:  # 极端情况：QtSvg 缺失时退回 loadFromData
    _HAS_SVG_RENDERER = False

from .. import config

_ICON_CACHE: dict[tuple, QIcon] = {}


def render_pixmap(name: str, color: str, size: int = 24, directory=None) -> QPixmap:
    """把 SVG 渲染成指定颜色和大小的 QPixmap（含高 DPI 支持）。"""
    path = (directory or config.ICONS_DIR) / f"{name}.svg"
    try:
        data = path.read_text(encoding="utf-8").replace("currentColor", color).encode("utf-8")
    except OSError:
        pm = QPixmap(size, size)
        pm.fill(Qt.transparent)
        return pm

    dpr = 1.0
    if QGuiApplication.instance() is not None:
        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            dpr = screen.devicePixelRatio()

    pm = QPixmap(int(size * dpr), int(size * dpr))
    pm.fill(Qt.transparent)
    painter = QPainter(pm)
    if _HAS_SVG_RENDERER:
        QSvgRenderer(QByteArray(data)).render(painter)
    else:
        raw = QPixmap()
        raw.loadFromData(data, "SVG")
        painter.drawPixmap(pm.rect(), raw)
    painter.end()
    pm.setDevicePixelRatio(dpr)
    return pm


def svg_icon(name: str, color: str, size: int = 24) -> QIcon:
    """单色图标（带缓存）。"""
    key = (name, color, size)
    if key not in _ICON_CACHE:
        _ICON_CACHE[key] = QIcon(render_pixmap(name, color, size))
    return _ICON_CACHE[key]


def nav_icon(name: str, on_color: str, off_color: str, size: int = 18) -> QIcon:
    """导航图标：未选中灰、选中主色（利用 QIcon Off/On 状态随按钮 checked 切换）。"""
    icon = QIcon()
    icon.addPixmap(render_pixmap(name, off_color, size), QIcon.Normal, QIcon.Off)
    icon.addPixmap(render_pixmap(name, on_color, size), QIcon.Normal, QIcon.On)
    return icon


def shadow_color() -> QColor:
    from . import theme

    r, g, b, a = theme.current()["shadow"]
    return QColor(r, g, b, a)


class Card(QFrame):
    """圆角卡片，带轻阴影。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        eff = QGraphicsDropShadowEffect(self)
        eff.setBlurRadius(18)
        eff.setOffset(0, 3)
        eff.setColor(shadow_color())
        self.setGraphicsEffect(eff)


class IconCircle(QLabel):
    """圆形浅色底 + 图标，用于空状态 / 占位页。"""

    def __init__(self, icon_name: str, size: int = 26, parent=None):
        super().__init__(parent)
        self._icon_name = icon_name
        self._size = size
        d = size * 2 + 16
        self.setFixedSize(d, d)
        self.setAlignment(Qt.AlignCenter)
        self.refresh_color()

    def refresh_color(self) -> None:
        from . import theme

        c = theme.current()
        radius = (self._size * 2 + 16) // 2
        self.setStyleSheet(
            f"QLabel {{ background: {c['primary_tint']}; border-radius: {radius}px; }}"
        )
        self.setPixmap(render_pixmap(self._icon_name, c["primary"], self._size))


class StatCard(Card):
    """仪表盘统计卡片：大数字 + 说明文字。"""

    def __init__(self, caption: str, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(4)
        self.value_label = QLabel("0")
        self.value_label.setObjectName("statValue")
        cap = QLabel(caption)
        cap.setObjectName("muted")
        lay.addWidget(self.value_label)
        lay.addWidget(cap)

    def set_value(self, value) -> None:
        self.value_label.setText(str(value))


# ---------------------------------------------------------------------------
# 状态徽章
# ---------------------------------------------------------------------------
def badge(text: str, color_key: str = "subtext") -> QLabel:
    """胶囊形徽章：浅色底 + 状态色文字（用半透明底色，亮暗主题通用）。"""
    from . import theme

    c = theme.current()
    base = c.get(color_key, c["subtext"])
    lbl = QLabel(text)
    lbl.setStyleSheet(
        f"QLabel {{ background: {base}1f; color: {base}; border-radius: 9px; "
        f"padding: 2px 9px; font-size: 12px; font-weight: 500; }}"
    )
    return lbl


def badge_cell(text: str, color_key: str) -> QWidget:
    """表格单元格用的徽章容器（带边距、居左）。"""
    container = QWidget()
    lay = QHBoxLayout(container)
    lay.setContentsMargins(6, 4, 6, 4)
    lay.addWidget(badge(text, color_key))
    lay.addStretch()
    return container


# ---------------------------------------------------------------------------
# 提醒弹窗（应用内，非阻塞，自动消失）
# ---------------------------------------------------------------------------
class ReminderPopup(QFrame):
    """右上角非模态提醒弹窗。"""

    def __init__(self, message: str, title: str, on_view=None, on_confirm=None, auto_close: bool = True):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setObjectName("card")
        self.setFixedWidth(320)
        self._on_view = on_view
        self._on_confirm = on_confirm

        eff = QGraphicsDropShadowEffect(self)
        eff.setBlurRadius(24)
        eff.setOffset(0, 4)
        eff.setColor(shadow_color())
        self.setGraphicsEffect(eff)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 14)
        lay.setSpacing(8)

        head = QLabel("🔔 实验提醒")
        head.setObjectName("cardTitle")
        msg = QLabel(message)
        msg.setObjectName("muted")
        body = QLabel(title)
        body.setWordWrap(True)
        body.setObjectName("statValue")

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        close_btn = QPushButton("知道了")
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.clicked.connect(self._confirm_and_close)
        view_btn = QPushButton("查看详情")
        view_btn.setCursor(Qt.PointingHandCursor)
        view_btn.clicked.connect(self._view)
        btn_row.addStretch()
        btn_row.addWidget(close_btn)
        btn_row.addWidget(view_btn)

        lay.addWidget(head)
        lay.addWidget(body)
        lay.addWidget(msg)
        lay.addLayout(btn_row)

        # 非到点提醒（如提前提醒）15 秒自动关闭；到点提醒不自动关，等用户确认
        if auto_close:
            QTimer.singleShot(15_000, self.close)

    def _confirm_and_close(self) -> None:
        if self._on_confirm is not None:
            self._on_confirm()
        self.close()

    def _view(self) -> None:
        if self._on_confirm is not None:
            self._on_confirm()
        if self._on_view is not None:
            self._on_view()
        self.close()

    def show_top_right(self) -> None:
        """从主屏右上角滑入显示。"""
        screen = QApplication.primaryScreen()
        if screen is not None:
            geo = screen.availableGeometry()
            self.adjustSize()
            target = QPoint(geo.right() - self.width() - 16, geo.top() + 16)
            start = QPoint(geo.right() + 20, target.y())
            self.move(start)
            self.show()
            anim = QPropertyAnimation(self, b"pos", self)
            anim.setDuration(220)
            anim.setStartValue(start)
            anim.setEndValue(target)
            anim.setEasingCurve(QEasingCurve.OutCubic)
            anim.start(QPropertyAnimation.DeleteWhenStopped)
            self._slide_anim = anim
        else:
            self.show()


def render_illustration(name: str, color: str, size: int = 160) -> QPixmap:
    """渲染 assets/illustrations/ 下的空状态插画。"""
    return render_pixmap(name, color, size, directory=config.ILLUSTRATIONS_DIR)


class EmptyState(QWidget):
    """空状态：插画 + 标题 + 描述。"""

    def __init__(self, title: str = "", desc: str = "", illustration: str = "empty", parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setAlignment(Qt.AlignCenter)
        lay.setSpacing(14)

        from . import theme

        c = theme.current()
        ill = QLabel()
        ill.setAlignment(Qt.AlignCenter)
        ill.setPixmap(render_illustration(illustration, c["subtext"], 150))
        lay.addWidget(ill)

        if title:
            t = QLabel(title)
            t.setObjectName("cardTitle")
            t.setAlignment(Qt.AlignCenter)
            lay.addWidget(t)
        if desc:
            d = QLabel(desc)
            d.setObjectName("muted")
            d.setWordWrap(True)
            d.setAlignment(Qt.AlignCenter)
            lay.addWidget(d)

    def on_theme_changed(self) -> None:
        from . import theme

        self.findChild(QLabel).setPixmap(
            render_illustration("empty", theme.current()["subtext"], 150))


IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp")

_IMG_PATH_RE = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")


def extract_markdown_images(text: str) -> list[str]:
    """从 Markdown 文本里提取图片相对路径（images/xxx.jpg）。"""
    return [m for m in _IMG_PATH_RE.findall(text or "") if m.startswith("images/")]


class ImageTextEdit(QPlainTextEdit):
    """图片文本编辑器：支持 Ctrl+V 粘贴截图、拖入图片文件（通过信号交由调用方处理）。"""

    paste_image = Signal(QImage)
    drop_image_file = Signal(str)

    def keyPressEvent(self, event) -> None:
        if event.matches(QKeySequence.Paste):
            mime = QApplication.clipboard().mimeData()
            if mime.hasImage():
                img = mime.imageData()
                if isinstance(img, QPixmap):
                    img = img.toImage()
                if isinstance(img, QImage) and not img.isNull():
                    self.paste_image.emit(img)
                    return
        super().keyPressEvent(event)

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls() or event.mimeData().hasImage():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dropEvent(self, event) -> None:
        files = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
        if files:
            for p in files:
                if p.lower().endswith(IMAGE_EXTS):
                    self.drop_image_file.emit(p)
            event.acceptProposedAction()
            return
        if event.mimeData().hasImage():
            img = event.mimeData().imageData()
            if isinstance(img, QPixmap):
                img = img.toImage()
            if isinstance(img, QImage) and not img.isNull():
                self.paste_image.emit(img)
            event.acceptProposedAction()
            return
        super().dropEvent(event)

    def focusOutEvent(self, event) -> None:
        """失焦时清除选中，避免点别处后还残留蓝色选中条。"""
        cursor = self.textCursor()
        if cursor.hasSelection():
            cursor.clearSelection()
            self.setTextCursor(cursor)
        super().focusOutEvent(event)

    def contextMenuEvent(self, event) -> None:
        """右键弹出标准菜单，但先清除选中，避免出现蓝条。"""
        cursor = self.textCursor()
        if cursor.hasSelection():
            cursor.clearSelection()
            self.setTextCursor(cursor)
        self.createStandardContextMenu().exec(event.globalPos())


class TextExpandDialog(QDialog):
    """大文本编辑对话框：展开编辑 + Markdown 工具栏（排版/图片/颜色）。"""

    def __init__(self, title: str, text: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(760, 600)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 16)
        lay.setSpacing(10)

        # 排版工具栏
        toolbar = QHBoxLayout()
        toolbar.setSpacing(4)
        for label, tip, slot in (
            ("B", "加粗", self._bold),
            ("I", "斜体", self._italic),
            ("H", "标题", self._heading),
            ("•", "列表", self._bullet),
            ("颜色", "字体颜色", self._color),
            ("图片", "插入图片", self._image),
        ):
            b = QPushButton(label)
            b.setCursor(Qt.PointingHandCursor)
            b.setToolTip(tip)
            b.clicked.connect(slot)
            toolbar.addWidget(b)
        toolbar.addStretch()
        lay.addLayout(toolbar)

        self.edit = ImageTextEdit()
        self.edit.setPlainText(text)
        self.edit.textChanged.connect(self._reload_images)
        lay.addWidget(self.edit, 1)

        self.images_flow = FlowLayout()
        lay.addLayout(self.images_flow)

        btns = QHBoxLayout()
        btns.addStretch()
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        ok = QPushButton("确定")
        ok.setObjectName("primaryBtn")
        ok.setDefault(True)
        ok.clicked.connect(self.accept)
        btns.addWidget(cancel)
        btns.addWidget(ok)
        lay.addLayout(btns)

        self._reload_images()

    def text(self) -> str:
        return self.edit.toPlainText()

    def _reload_images(self) -> None:
        """从文本实时解析图片路径，显示缩略图（编辑时能直接看到图片）。"""
        while self.images_flow.count():
            item = self.images_flow.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        for rel in extract_markdown_images(self.edit.toPlainText()):
            thumb = ClickableImageLabel(rel, max_edge=120)
            thumb.clicked.connect(lambda p=rel: self._preview(p))
            self.images_flow.addWidget(thumb)

    def _preview(self, rel: str) -> None:
        from ..utils import image_utils

        pm = image_utils.load_pixmap(rel)
        if pm is not None:
            ImagePreviewDialog(pm, rel.split("/")[-1], self).exec()

    # ---- 工具栏操作（往 Markdown 文本插入对应语法）----
    def _wrap_selection(self, prefix: str, suffix: str) -> None:
        cur = self.edit.textCursor()
        sel = cur.selectedText()
        if sel:
            cur.insertText(prefix + sel + suffix)
        else:
            cur.insertText(prefix + suffix)
            cur.movePosition(QTextCursor.Left, QTextCursor.MoveAnchor, len(suffix))
            self.edit.setTextCursor(cur)
        self.edit.setFocus()

    def _bold(self) -> None:
        self._wrap_selection("**", "**")

    def _italic(self) -> None:
        self._wrap_selection("*", "*")

    def _heading(self) -> None:
        cur = self.edit.textCursor()
        cur.movePosition(QTextCursor.StartOfLine)
        cur.insertText("# ")
        self.edit.setFocus()

    def _bullet(self) -> None:
        cur = self.edit.textCursor()
        cur.movePosition(QTextCursor.StartOfLine)
        cur.insertText("- ")
        self.edit.setFocus()

    def _color(self) -> None:
        color = QColorDialog.getColor(parent=self)
        if color.isValid():
            self._wrap_selection(f'<font color="{color.name()}">', "</font>")

    def _image(self) -> None:
        from ..utils import image_utils

        paths, _ = QFileDialog.getOpenFileNames(
            self, "插入图片", "", "图片 (*.png *.jpg *.jpeg *.gif *.bmp *.webp)")
        for p in paths:
            rel = image_utils.save_image_file(p)
            if rel:
                self.edit.insertPlainText(f"![图片]({rel})")
        self.edit.setFocus()


def make_expand_button(edit, title: str) -> QPushButton:
    """生成“展开”按钮：点击弹出大窗口编辑 edit 的内容，确定后写回。"""
    btn = QPushButton("⤢ 展开")
    btn.setCursor(Qt.PointingHandCursor)

    def _expand() -> None:
        dlg = TextExpandDialog(title, edit.toPlainText(), edit.window())
        if dlg.exec() == QDialog.Accepted:
            edit.setPlainText(dlg.text())

    btn.clicked.connect(_expand)
    return btn


class FlowLayout(QLayout):
    """流式布局：子项按行排列，超出宽度自动换行（用于多张图片展示）。"""

    def __init__(self, parent=None, margin: int = 0, spacing: int = 8):
        super().__init__(parent)
        self._items = []
        self.setContentsMargins(margin, margin, margin, margin)
        self.setSpacing(spacing)

    def addItem(self, item) -> None:
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int):
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientations()

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._do_layout(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect: QRect) -> None:
        super().setGeometry(rect)
        self._do_layout(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        return size + QSize(m.left() + m.right(), m.top() + m.bottom())

    def _do_layout(self, rect: QRect, test_only: bool) -> int:
        m = self.contentsMargins()
        effective = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        x, y = effective.x(), effective.y()
        line_height = 0
        for item in self._items:
            hint = item.sizeHint()
            if x + hint.width() > effective.right() + 1 and line_height > 0:
                x = effective.x()
                y += line_height + self.spacing()
                line_height = 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + self.spacing()
            line_height = max(line_height, hint.height())
        return y + line_height - rect.y() + m.bottom()


class ClickableImageLabel(QLabel):
    """可点击的图片标签：直接以大图展示，点击发出信号（用于预览）。"""

    clicked = Signal(str)  # 图片相对路径

    def __init__(self, path: str, max_edge: int = 260, parent=None):
        super().__init__(parent)
        self._path = path
        self.setCursor(Qt.PointingHandCursor)
        from ..utils import image_utils

        pm = image_utils.load_pixmap(path, max_edge)
        if pm is not None and not pm.isNull():
            self.setPixmap(pm)
            self.setFixedSize(pm.width(), pm.height())
        else:
            self.setText("（图片加载失败）")
            self.setObjectName("muted")

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self._path)
        super().mousePressEvent(event)


class TypeManagerDialog(QDialog):
    """管理实验类型清单：每行一个类型，可增删，保存到 settings。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("管理实验类型")
        self.setMinimumWidth(380)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(10)

        tip = QLabel("每行一个实验类型（任务种类），可自由增删改。")
        tip.setObjectName("muted")
        tip.setWordWrap(True)
        lay.addWidget(tip)

        from ..models import experiment

        self.edit = QPlainTextEdit()
        self.edit.setPlaceholderText("例如：\n合成质粒\n细胞培养\n显微镜观察")
        self.edit.setPlainText("\n".join(experiment.get_types()))
        self.edit.setFixedHeight(220)
        lay.addWidget(self.edit)

        row = QHBoxLayout()
        row.addStretch()
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        save = QPushButton("保存")
        save.setDefault(True)
        save.clicked.connect(self.accept)
        row.addWidget(cancel)
        row.addWidget(save)
        lay.addLayout(row)

    def accept(self) -> None:
        from ..models import experiment

        types = [t.strip() for t in self.edit.toPlainText().splitlines() if t.strip()]
        experiment.set_types(types)
        super().accept()


class ImagePreviewDialog(QDialog):
    """图片放大预览（简单弹窗，M5 再做动画）。"""

    def __init__(self, pixmap: QPixmap, title: str = "图片预览", parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(720, 560)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(12)

        screen = QApplication.primaryScreen()
        avail = screen.availableGeometry() if screen else None
        max_w = int(avail.width() * 0.85) if avail else 1200
        max_h = int(avail.height() * 0.8) if avail else 800
        if pixmap.width() > max_w or pixmap.height() > max_h:
            pixmap = pixmap.scaled(max_w, max_h, Qt.KeepAspectRatio, Qt.SmoothTransformation)

        img = QLabel()
        img.setPixmap(pixmap)
        img.setAlignment(Qt.AlignCenter)
        lay.addWidget(img, 1)

        row = QHBoxLayout()
        row.addStretch()
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.accept)
        row.addWidget(close_btn)
        lay.addLayout(row)

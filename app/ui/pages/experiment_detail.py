"""实验详情页：信息展示 + 状态流转 + 实验记录时间线（文字/Markdown/图片）。

时间线用自定义 Widget 逐条渲染（每条记录一张卡），图片以独立缩略图展示
而非塞进 QTextEdit/QTextBrowser，避免大量图片导致卡顿。
图片：文件选择 / 拖拽 / 粘贴截图（Ctrl+V）三种方式，统一压缩为 JPG 存 data/images/。
"""
from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QDateTime, QSize, Qt, Signal
from PySide6.QtGui import QIcon, QImage, QKeySequence, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QDateTimeEdit,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ... import config
from ...models import experiment, record
from ...utils import image_utils, markdown_utils, time_utils
from ..components import (
    IMAGE_EXTS,
    Card,
    ClickableImageLabel,
    FlowLayout,
    ImagePreviewDialog,
    ImageTextEdit,
    badge,
    make_expand_button,
)

class _RecordCard(Card):
    """时间线里的一条记录。"""

    def __init__(self, rec: dict, images: list[dict], on_delete, on_image_click):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(10)

        # 时间 + 删除
        header = QHBoxLayout()
        header.setSpacing(8)
        time_lbl = QLabel(rec["record_time"])
        time_lbl.setObjectName("muted")
        del_btn = QPushButton("删除")
        del_btn.setCursor(Qt.PointingHandCursor)
        del_btn.clicked.connect(lambda: on_delete(rec["id"]))
        header.addWidget(time_lbl)
        header.addStretch()
        header.addWidget(del_btn)
        lay.addLayout(header)

        # 正文（Markdown -> 富文本）
        content = (rec["content"] or "").strip()
        if content:
            body = QLabel()
            body.setTextFormat(Qt.RichText)
            body.setWordWrap(True)
            body.setTextInteractionFlags(Qt.TextSelectableByMouse)
            body.setText(markdown_utils.to_html(content))
            lay.addWidget(body)

        # 图片：直接以大图展示，多图自动换行，点击放大预览
        if images:
            flow = FlowLayout()
            for img in images:
                lbl = ClickableImageLabel(img["path"])
                lbl.clicked.connect(on_image_click)
                flow.addWidget(lbl)
            lay.addLayout(flow)


class _AddRecordPanel(QWidget):
    """添加记录面板：时间 + 正文 + 图片（暂存，保存时落库）。"""

    saved = Signal(int)

    def __init__(self, experiment_id: int):
        super().__init__()
        self.experiment_id = experiment_id
        self._images: list[str] = []  # 相对路径，保存前暂存
        self.setObjectName("card")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAcceptDrops(True)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(10)

        self.body_edit = ImageTextEdit()
        self.body_edit.setPlaceholderText("记录内容，支持 Markdown；可直接粘贴截图（Ctrl+V）或拖入图片")
        self.body_edit.setFixedHeight(110)
        self.body_edit.paste_image.connect(self._add_qimage)
        self.body_edit.drop_image_file.connect(self._add_image_file)

        time_row = QHBoxLayout()
        time_row.addWidget(QLabel("记录时间"))
        self.time_edit = QDateTimeEdit(QDateTime.currentDateTime())
        self.time_edit.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
        self.time_edit.setCalendarPopup(True)
        time_row.addWidget(self.time_edit)
        time_row.addStretch()
        time_row.addWidget(make_expand_button(self.body_edit, "记录内容"))
        lay.addLayout(time_row)
        lay.addWidget(self.body_edit)

        self.img_row = QHBoxLayout()
        self.img_row.setSpacing(8)
        self.img_row.addStretch()
        lay.addLayout(self.img_row)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        insert_btn = QPushButton("插入图片")
        insert_btn.setCursor(Qt.PointingHandCursor)
        insert_btn.clicked.connect(self._choose_files)
        save_btn = QPushButton("保存记录")
        save_btn.setCursor(Qt.PointingHandCursor)
        save_btn.setDefault(True)
        save_btn.clicked.connect(self._save)
        cancel_btn = QPushButton("取消")
        cancel_btn.setCursor(Qt.PointingHandCursor)
        cancel_btn.clicked.connect(self._cancel)
        btn_row.addWidget(insert_btn)
        btn_row.addStretch()
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(save_btn)
        lay.addLayout(btn_row)

    # ---- 图片 ----
    def _add_qimage(self, img: QImage) -> None:
        rel = image_utils.save_image(img)
        self._register(rel)

    def _add_image_file(self, path: str) -> None:
        rel = image_utils.save_image_file(path)
        if rel:
            self._register(rel)

    def _register(self, rel: str) -> None:
        self._images.append(rel)
        self.body_edit.appendPlainText(f"![图片]({rel})")
        self._rebuild_image_row()

    def _rebuild_image_row(self) -> None:
        while self.img_row.count() > 1:  # 保留末尾 stretch
            item = self.img_row.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        for rel in self._images:
            self.img_row.insertWidget(self.img_row.count() - 1, self._pending_thumb(rel))

    def _pending_thumb(self, rel: str) -> QWidget:
        wrap = QWidget()
        v = QVBoxLayout(wrap)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(2)
        btn = QToolButton()
        pm = image_utils.load_pixmap(rel, 160)
        if pm is not None:
            btn.setIcon(QIcon(pm))
        btn.setIconSize(QSize(80, 80))
        btn.setFixedSize(88, 88)
        btn.clicked.connect(lambda: self._preview(rel))
        rm = QPushButton("移除")
        rm.setCursor(Qt.PointingHandCursor)
        rm.clicked.connect(lambda: self._remove_image(rel))
        v.addWidget(btn)
        v.addWidget(rm)
        return wrap

    def _remove_image(self, rel: str) -> None:
        if rel in self._images:
            self._images.remove(rel)
            image_utils.delete_image(rel)
            self._rebuild_image_row()

    def _preview(self, rel: str) -> None:
        pm = image_utils.load_pixmap(rel)
        if pm is not None:
            ImagePreviewDialog(pm, rel.split("/")[-1], self).exec()

    def _choose_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, "选择图片", "", "图片 (*.png *.jpg *.jpeg *.gif *.bmp *.webp)"
        )
        for p in paths:
            self._add_image_file(p)

    # ---- 拖拽 ----
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
                    self._add_image_file(p)
            event.acceptProposedAction()
            return
        if event.mimeData().hasImage():
            img = event.mimeData().imageData()
            if isinstance(img, QPixmap):
                img = img.toImage()
            if isinstance(img, QImage) and not img.isNull():
                self._add_qimage(img)
            event.acceptProposedAction()
            return
        super().dropEvent(event)

    # ---- 保存 / 取消 ----
    def _save(self) -> None:
        content = self.body_edit.toPlainText()
        if not content.strip() and not self._images:
            QMessageBox.information(self, config.APP_NAME, "记录内容为空，请填写内容或添加图片。")
            return
        rec_id = record.create_record(
            self.experiment_id, content,
            self.time_edit.dateTime().toString("yyyy-MM-dd HH:mm:ss"),
        )
        for rel in self._images:
            record.add_image(rec_id, self.experiment_id, rel)
        self._images = []
        self._reset()
        self.saved.emit(rec_id)

    def _cancel(self) -> None:
        for rel in self._images:
            image_utils.delete_image(rel)
        self._images = []
        self._reset()
        self.saved.emit(-1)  # -1 表示取消，父级仅隐藏面板

    def _reset(self) -> None:
        self.body_edit.clear()
        self.time_edit.setDateTime(QDateTime.currentDateTime())
        self._rebuild_image_row()

    def reset_for_new(self) -> None:
        """展开面板时重置为当前时间。"""
        self.time_edit.setDateTime(QDateTime.currentDateTime())
        self.body_edit.clear()


class ExperimentDetailPage(QWidget):
    back_requested = Signal()
    edit_requested = Signal(int)
    deleted = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.exp_id: int | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 20, 28, 24)
        outer.setSpacing(14)

        # 顶栏：返回 + 标题 + 徽章 + 编辑/删除
        top = QHBoxLayout()
        top.setSpacing(10)
        self.back_btn = QPushButton("← 返回")
        self.back_btn.setCursor(Qt.PointingHandCursor)
        self.back_btn.clicked.connect(self.back_requested.emit)
        self.title_label = QLabel()
        self.title_label.setObjectName("pageTitle")
        self.status_badge = QLabel()
        self.priority_badge = QLabel()
        self.remind_badge = QLabel()
        self.edit_btn = QPushButton("编辑")
        self.edit_btn.setCursor(Qt.PointingHandCursor)
        self.del_btn = QPushButton("删除")
        self.del_btn.setCursor(Qt.PointingHandCursor)
        self.edit_btn.clicked.connect(lambda: self.edit_requested.emit(self.exp_id or 0))
        self.del_btn.clicked.connect(self._confirm_delete)

        top.addWidget(self.back_btn)
        top.addWidget(self.title_label)
        top.addWidget(self.status_badge)
        top.addWidget(self.priority_badge)
        top.addWidget(self.remind_badge)
        top.addStretch()
        top.addWidget(self.edit_btn)
        top.addWidget(self.del_btn)
        outer.addLayout(top)

        # 信息区
        info_row = QHBoxLayout()
        info_row.setSpacing(14)
        left_card = Card()
        left = QVBoxLayout(left_card)
        left.setContentsMargins(20, 16, 20, 16)
        left.setSpacing(8)
        self.goal_label = QLabel()
        self.goal_label.setWordWrap(True)
        self.goal_label.setObjectName("muted")
        self.steps_label = QLabel()
        self.steps_label.setWordWrap(True)
        self.steps_label.setObjectName("muted")
        left.addWidget(QLabel("目标 / 步骤"))
        left.addWidget(self.goal_label)
        left.addWidget(self.steps_label)
        left.addStretch()
        info_row.addWidget(left_card, 2)

        right_card = Card()
        right = QVBoxLayout(right_card)
        right.setContentsMargins(20, 16, 20, 16)
        right.setSpacing(8)
        right.addWidget(QLabel("时间信息"))
        self.time_label = QLabel()
        self.time_label.setWordWrap(True)
        self.time_label.setObjectName("muted")
        self.tags_label = QLabel()
        self.tags_label.setWordWrap(True)
        self.tags_label.setObjectName("muted")
        self.notes_label = QLabel()
        self.notes_label.setWordWrap(True)
        self.notes_label.setObjectName("muted")
        right.addWidget(self.time_label)
        right.addWidget(self.tags_label)
        right.addWidget(self.notes_label)
        right.addStretch()
        self.actions_row = QHBoxLayout()
        self.actions_row.setSpacing(8)
        right.addLayout(self.actions_row)
        info_row.addWidget(right_card, 1)
        outer.addLayout(info_row, 1)

        # 实验结论（周整理可引用）
        conclusion_card = Card()
        cc = QVBoxLayout(conclusion_card)
        cc.setContentsMargins(20, 14, 20, 14)
        cc.setSpacing(8)

        self.conclusion_edit = ImageTextEdit()
        self.conclusion_edit.setPlaceholderText("记录本实验的结论；可直接粘贴截图（Ctrl+V）或拖入图片…")
        self.conclusion_edit.setFixedHeight(72)
        self.conclusion_edit.textChanged.connect(self._mark_conclusion_dirty)
        self.conclusion_edit.paste_image.connect(self._add_conclusion_qimage)
        self.conclusion_edit.drop_image_file.connect(self._add_conclusion_file)

        chead = QHBoxLayout()
        cl = QLabel("实验结论")
        cl.setObjectName("cardTitle")
        self.conclusion_save_label = QLabel("")
        self.conclusion_save_label.setObjectName("muted")
        expand_btn = make_expand_button(self.conclusion_edit, "实验结论")
        concl_img_btn = QPushButton("插入图片")
        concl_img_btn.setCursor(Qt.PointingHandCursor)
        concl_img_btn.clicked.connect(self._choose_conclusion_image)
        concl_save_btn = QPushButton("保存")
        concl_save_btn.setObjectName("primaryBtn")
        concl_save_btn.setCursor(Qt.PointingHandCursor)
        concl_save_btn.clicked.connect(self._save_conclusion)
        chead.addWidget(cl)
        chead.addStretch()
        chead.addWidget(self.conclusion_save_label)
        chead.addWidget(expand_btn)
        chead.addWidget(concl_img_btn)
        chead.addWidget(concl_save_btn)
        cc.addLayout(chead)
        cc.addWidget(self.conclusion_edit)
        self.conclusion_images_flow = FlowLayout()
        cc.addLayout(self.conclusion_images_flow)
        outer.addWidget(conclusion_card)

        # 记录时间线卡片
        records_card = Card()
        rc = QVBoxLayout(records_card)
        rc.setContentsMargins(20, 16, 20, 16)
        rc.setSpacing(10)
        rec_head = QHBoxLayout()
        rec_title = QLabel("实验记录")
        rec_title.setObjectName("cardTitle")
        self.add_btn = QPushButton("＋ 添加记录")
        self.add_btn.setCursor(Qt.PointingHandCursor)
        self.add_btn.clicked.connect(self._toggle_add)
        rec_head.addWidget(rec_title)
        rec_head.addStretch()
        rec_head.addWidget(self.add_btn)
        rc.addLayout(rec_head)

        self.add_panel = _AddRecordPanel(self.exp_id or 0)
        self.add_panel.saved.connect(self._on_record_saved)
        self.add_panel.hide()
        rc.addWidget(self.add_panel)

        self.timeline_scroll = QScrollArea()
        self.timeline_scroll.setWidgetResizable(True)
        self.timeline_scroll.setFrameShape(QScrollArea.NoFrame)
        self.timeline_container = QWidget()
        self.timeline_layout = QVBoxLayout(self.timeline_container)
        self.timeline_layout.setContentsMargins(0, 0, 0, 0)
        self.timeline_layout.setSpacing(10)
        self.timeline_layout.addStretch()
        self.timeline_scroll.setWidget(self.timeline_container)
        rc.addWidget(self.timeline_scroll, 1)
        outer.addWidget(records_card, 2)

        self._build_status_actions()

    def _build_status_actions(self) -> None:
        defs = [
            ("开始实验", lambda: experiment.mark_started(self.exp_id)),
            ("完成", lambda: experiment.mark_finished(self.exp_id)),
            ("失败", lambda: experiment.set_status(self.exp_id, "failed")),
            ("暂停", lambda: experiment.set_status(self.exp_id, "paused")),
        ]
        self._action_btns = []
        for text, fn in defs:
            b = QPushButton(text)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, f=fn: (f(), self.load(self.exp_id)))
            self.actions_row.addWidget(b)
            self._action_btns.append(b)

    # ------------------------------------------------------------------ 记录

    def _toggle_add(self) -> None:
        if self.add_panel.isVisible():
            self.add_panel.hide()
        else:
            self.add_panel.experiment_id = self.exp_id or 0
            self.add_panel.reset_for_new()
            self.add_panel.show()

    def _on_record_saved(self, rec_id: int) -> None:
        if rec_id != -1:
            self.add_panel.hide()
        self._reload_records()

    def _reload_records(self) -> None:
        # 清空旧卡片（保留末尾 stretch）
        while self.timeline_layout.count() > 1:
            item = self.timeline_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        if self.exp_id is None:
            return
        records = record.list_records(self.exp_id)
        if not records:
            empty = QLabel("暂无记录，点击右上角「＋ 添加记录」开始。")
            empty.setObjectName("muted")
            self.timeline_layout.insertWidget(0, empty)
            return
        for rec in records:
            imgs = record.list_images_for_record(rec["id"])
            card = _RecordCard(rec, imgs, self._delete_record, self._preview_image)
            self.timeline_layout.insertWidget(self.timeline_layout.count() - 1, card)

    def _delete_record(self, rec_id: int) -> None:
        ret = QMessageBox.question(self, config.APP_NAME, "确定删除这条记录吗？（含其中的图片）")
        if ret == QMessageBox.Yes:
            record.delete_record(rec_id)
            self._reload_records()

    def _preview_image(self, rel: str) -> None:
        pm = image_utils.load_pixmap(rel)
        if pm is not None:
            ImagePreviewDialog(pm, rel.split("/")[-1], self).exec()

    # ------------------------------------------------------------------ 数据

    def load(self, exp_id: int) -> None:
        self.exp_id = exp_id
        exp = experiment.get(exp_id)
        if exp is None:
            self.title_label.setText("（实验不存在或已删除）")
            return
        self.title_label.setText(exp["title"])
        self._set_badge(self.status_badge, experiment.STATUS_LABELS.get(exp["status"], exp["status"]),
                        experiment.STATUS_COLORS.get(exp["status"], "subtext"))
        self._set_badge(self.priority_badge,
                        "优先级 " + experiment.PRIORITY_LABELS.get(exp["priority"], "中"),
                        experiment.PRIORITY_COLORS.get(exp["priority"], "subtext"))
        remind = "🔔 提醒已开" if exp["remind_enabled"] else "提醒未开"
        self._set_badge(self.remind_badge, remind, "primary" if exp["remind_enabled"] else "subtext")

        self.goal_label.setText(exp["goal"] or "（未填写目标）")
        self.steps_label.setText(exp["steps"] or "（未填写步骤）")

        lines = [
            f"计划：{exp['planned_start'] or '—'} → {exp['planned_end'] or '—'}"
            f"（{time_utils.format_duration(exp['duration_min'])}）",
            f"实际开始：{exp['actual_start'] or '—'}",
            f"实际结束：{exp['actual_end'] or '—'}",
        ]
        self.time_label.setText("\n".join(lines))
        self.tags_label.setText(f"标签：{experiment.tags_to_str(exp) or '—'}")
        self.notes_label.setText(f"备注：{exp['notes'] or '—'}")

        self.conclusion_edit.blockSignals(True)
        self.conclusion_edit.setPlainText(exp.get("conclusion") or "")
        self.conclusion_edit.blockSignals(False)
        self.conclusion_save_label.setText("")
        self._reload_conclusion_images()

        self.add_panel.experiment_id = exp_id
        self._reload_records()

    # ------------------------------------------------------------------ 结论

    def _mark_conclusion_dirty(self) -> None:
        self.conclusion_save_label.setText("未保存")

    def _save_conclusion(self) -> None:
        if self.exp_id is None:
            return
        experiment.save_conclusion(self.exp_id, self.conclusion_edit.toPlainText())
        self.conclusion_save_label.setText("已保存")

    # ------------------------------------------------------------------ 结论图片

    def _choose_conclusion_image(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, "选择图片", "", "图片 (*.png *.jpg *.jpeg *.gif *.bmp *.webp)"
        )
        for p in paths:
            self._add_conclusion_file(p)

    def _add_conclusion_qimage(self, img: QImage) -> None:
        rel = image_utils.save_image(img)
        self._register_conclusion_image(rel)

    def _add_conclusion_file(self, path: str) -> None:
        rel = image_utils.save_image_file(path)
        if rel:
            self._register_conclusion_image(rel)

    def _register_conclusion_image(self, rel: str) -> None:
        if self.exp_id is None:
            return
        record.add_conclusion_image(self.exp_id, rel)
        self.conclusion_edit.appendPlainText(f"![图片]({rel})")
        self._reload_conclusion_images()

    def _reload_conclusion_images(self) -> None:
        while self.conclusion_images_flow.count():
            item = self.conclusion_images_flow.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        if self.exp_id is None:
            return
        for img in record.list_conclusion_images(self.exp_id):
            self.conclusion_images_flow.addWidget(self._conclusion_image_thumb(img))

    def _conclusion_image_thumb(self, img: dict) -> QWidget:
        wrap = QWidget()
        v = QVBoxLayout(wrap)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(2)
        thumb = ClickableImageLabel(img["path"], max_edge=140)
        thumb.clicked.connect(lambda p=img["path"]: self._preview_image(p))
        rm = QPushButton("移除")
        rm.setCursor(Qt.PointingHandCursor)
        rm.clicked.connect(
            lambda _=False, iid=img["id"], p=img["path"]: self._remove_conclusion_image(iid, p)
        )
        v.addWidget(thumb)
        v.addWidget(rm)
        return wrap

    def _remove_conclusion_image(self, image_id: int, path: str) -> None:
        record.delete_conclusion_image(image_id)
        txt = self.conclusion_edit.toPlainText().replace(f"![图片]({path})", "")
        self.conclusion_edit.setPlainText(txt)
        self._reload_conclusion_images()

    def _set_badge(self, target: QLabel, text: str, color_key: str) -> None:
        b = badge(text, color_key)
        target.setText(b.text())
        target.setStyleSheet(b.styleSheet())

    def _confirm_delete(self) -> None:
        if self.exp_id is None:
            return
        exp = experiment.get(self.exp_id)
        if exp is None:
            return
        ret = QMessageBox.question(
            self, config.APP_NAME,
            f"确定删除实验「{exp['title']}」吗？\n相关记录与图片将一并删除。",
        )
        if ret == QMessageBox.Yes:
            # 删除前清理所有图片文件
            for img in record.list_images(self.exp_id):
                image_utils.delete_image(img["path"])
            experiment.delete(self.exp_id)
            eid = self.exp_id
            self.exp_id = None
            self.deleted.emit(eid)

    def on_theme_changed(self) -> None:
        if self.exp_id is not None:
            self.load(self.exp_id)

"""实验规划页：下周七天视图 + 拖拽排序/跨天/跨周 + 一键转实验。

- 默认显示下一周
- 卡片拖拽（QDrag）：同周内跨天移动 + 列内排序；拖到顶部“上一周/下一周”投放区跨周移动
- 拖拽落点按 y 坐标计算插入位置，落定后重排 sort_order 并持久化
- 底部统计周总时长、每日数量/时长，冲突红点提示
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta

from PySide6.QtCore import QDate, QMimeData, QTime, Qt, Signal
from PySide6.QtGui import QColor, QDrag, QPainter
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDateEdit,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from ... import config
from ...models import experiment as exp_model
from ...models import weekly
from ...utils import time_utils
from ..components import Card, badge
from .experiment_form import ExperimentCoreForm

_PLAN_STATUS = {"planned": "未开始", "converted": "已转实验", "done": "已完成", "cancelled": "已取消"}
_PLAN_STATUS_COLORS = {"planned": "subtext", "converted": "primary", "done": "success", "cancelled": "subtext"}
_WEEKDAY_CN = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")


def _priority_color(key: str) -> str:
    from .. import theme

    return theme.current().get(exp_model.PRIORITY_COLORS.get(key, "subtext"), "#9CA3AF")


def _parse_list(value) -> list:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            value = []
    return value if isinstance(value, list) else []


# ---------------------------------------------------------------------------
# 快速添加弹窗
# ---------------------------------------------------------------------------
class PlanItemDialog(QDialog):
    """添加/编辑规划项。

    普通模式只填基本排期；“实验计划”模式复用 ExperimentCoreForm，
    与实验界面字段完全一致（目标/步骤/提醒/跟随实验），转实验时不用重写。
    """

    def __init__(self, default_date: str, parent=None, item_id: int | None = None):
        super().__init__(parent)
        self.item_id = item_id
        self.default_date = default_date
        self.saved_id: int | None = None
        self.setWindowTitle("编辑规划项" if item_id else "添加规划项")
        self.setMinimumSize(600, 660)
        self.resize(680, 780)
        self._build_ui()
        if item_id is not None:
            self._load(item_id)
        else:
            d = datetime.strptime(default_date, "%Y-%m-%d").date()
            self.simple_date.setDate(QDate(d.year, d.month, d.day))
            self.simple_time.setTime(QTime(9, 0))
            self.exp_form.set_basic("", "", "medium", default_date, "09:00", 0, "")
        self._on_mode_changed()

    # ------------------------------------------------------------------ 构建

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(10)

        mode_row = QHBoxLayout()
        mode_row.setSpacing(8)
        mode_row.addWidget(QLabel("规划类型"))
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("普通规划项", 0)
        self.mode_combo.addItem("实验计划（完整实验信息）", 1)
        self.mode_combo.currentIndexChanged.connect(lambda *_: self._on_mode_changed())
        mode_row.addWidget(self.mode_combo)
        tip = QLabel("选“实验计划”后字段与实验界面一致，一键转实验不用重填")
        tip.setObjectName("muted")
        mode_row.addWidget(tip)
        mode_row.addStretch()
        root.addLayout(mode_row)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.NoFrame)
        host = QWidget()
        host_lay = QVBoxLayout(host)
        host_lay.setContentsMargins(2, 2, 8, 8)
        host_lay.setSpacing(10)
        self.simple_form = self._build_simple_form()
        self.exp_form = ExperimentCoreForm(
            show_template_picker=True, show_actual_status=False)
        host_lay.addWidget(self.simple_form)
        host_lay.addWidget(self.exp_form)
        host_lay.addStretch()
        self.scroll.setWidget(host)
        root.addWidget(self.scroll, 1)

        btns = QHBoxLayout()
        btns.addStretch()
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        save = QPushButton("保存")
        save.setObjectName("primaryBtn")
        save.setDefault(True)
        save.clicked.connect(self._accept)
        btns.addWidget(cancel)
        btns.addWidget(save)
        root.addLayout(btns)

    def _build_simple_form(self) -> QWidget:
        from PySide6.QtWidgets import QFormLayout

        wrap = QWidget()
        form = QFormLayout(wrap)
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignRight)

        self.simple_title = QLineEdit()
        self.simple_title.setPlaceholderText("标题（必填）")
        self.simple_type = QComboBox()
        self.simple_type.setEditable(True)
        self.simple_type.addItem("")
        for t in exp_model.all_types():
            self.simple_type.addItem(t)
        self.simple_date = QDateEdit(QDate.currentDate())
        self.simple_date.setCalendarPopup(True)
        self.simple_date.setDisplayFormat("yyyy-MM-dd")
        self.simple_time = QTimeEdit(QTime(9, 0))
        self.simple_time.setDisplayFormat("HH:mm")
        self.simple_hour = QSpinBox()
        self.simple_hour.setRange(0, 999)
        self.simple_hour.setSuffix(" 小时")
        self.simple_min = QSpinBox()
        self.simple_min.setRange(0, 59)
        self.simple_min.setSuffix(" 分钟")
        dur_row = QHBoxLayout()
        dur_row.addWidget(self.simple_hour)
        dur_row.addWidget(self.simple_min)
        dur_widget = QWidget()
        dur_widget.setLayout(dur_row)
        self.simple_end = QLabel("—")
        self.simple_end.setObjectName("cardTitle")
        self.simple_priority = QComboBox()
        for k, v in exp_model.PRIORITY_LABELS.items():
            self.simple_priority.addItem(v, k)
        self.simple_priority.setCurrentIndex(1)
        self.simple_notes = QPlainTextEdit()
        self.simple_notes.setFixedHeight(64)
        self.simple_notes.setPlaceholderText("备注")

        form.addRow("标题 *", self.simple_title)
        form.addRow("类型", self.simple_type)
        form.addRow("日期", self.simple_date)
        form.addRow("开始时间", self.simple_time)
        form.addRow("预计耗时", dur_widget)
        form.addRow("预计结束", self.simple_end)
        form.addRow("优先级", self.simple_priority)
        form.addRow("备注", self.simple_notes)

        self.simple_date.dateChanged.connect(lambda *_: self._recompute_simple())
        self.simple_time.timeChanged.connect(lambda *_: self._recompute_simple())
        self.simple_hour.valueChanged.connect(lambda *_: self._recompute_simple())
        self.simple_min.valueChanged.connect(lambda *_: self._recompute_simple())
        self._recompute_simple()
        return wrap

    def _duration(self) -> int:
        return self.simple_hour.value() * 60 + self.simple_min.value()

    def _recompute_simple(self) -> None:
        start = self.simple_time.time().toString("HH:mm")
        dur = self._duration()
        if dur > 0:
            end = time_utils.minutes_to_time(time_utils.time_to_minutes(start) + dur)
            self.simple_end.setText(f"{end}（跨天）" if end < start else end)
        else:
            self.simple_end.setText("—")

    # ------------------------------------------------------------------ 模式切换

    def _on_mode_changed(self, copy: bool = True) -> None:
        is_exp = self.mode_combo.currentData() == 1
        if copy and is_exp:
            self.exp_form.set_basic(
                self.simple_title.text().strip(),
                self.simple_type.currentText().strip(),
                self.simple_priority.currentData(),
                self.simple_date.date().toString("yyyy-MM-dd"),
                self.simple_time.time().toString("HH:mm"),
                self._duration(),
                self.simple_notes.toPlainText(),
            )
        elif copy:
            data = self.exp_form.collect()
            self.simple_title.setText(data.get("title") or "")
            self.simple_type.setCurrentText(data.get("type") or "")
            idx = self.simple_priority.findData(data.get("priority"))
            self.simple_priority.setCurrentIndex(idx if idx >= 0 else 1)
            start = data.get("planned_start") or ""
            if start:
                d = QDate.fromString(start[:10], "yyyy-MM-dd")
                t = QTime.fromString(start[11:16], "HH:mm")
                if d.isValid():
                    self.simple_date.setDate(d)
                if t.isValid():
                    self.simple_time.setTime(t)
            dur = int(data.get("duration_min") or 0)
            self.simple_hour.setValue(dur // 60)
            self.simple_min.setValue(dur % 60)
            self.simple_notes.setPlainText(data.get("notes") or "")
            self._recompute_simple()
        self.simple_form.setVisible(not is_exp)
        self.exp_form.setVisible(is_exp)

    # ------------------------------------------------------------------ 载入

    def _load(self, item_id: int) -> None:
        item = weekly.get_item(item_id)
        if item is None:
            return
        linked_id = item.get("linked_experiment_id")
        if linked_id:
            exp = exp_model.get(int(linked_id))
            if exp is not None:
                item = dict(item)
                item.update({
                    "title": exp["title"], "type": exp["type"],
                    "goal": exp["goal"], "steps": exp["steps"],
                    "tags": exp["tags"], "notes": exp["notes"],
                    "remind_enabled": exp["remind_enabled"],
                    "remind_advance_min": exp["remind_advance_min"],
                    "remind_on_time": exp["remind_on_time"],
                    "remind_end_min": exp["remind_end_min"],
                    "followups": exp_model.followup_specs(int(linked_id)),
                })
        self.simple_title.setText(item.get("title") or "")
        self.simple_type.setCurrentText(item.get("type") or "")
        d = QDate.fromString(item.get("planned_date") or self.default_date, "yyyy-MM-dd")
        if d.isValid():
            self.simple_date.setDate(d)
        t = QTime.fromString(item.get("planned_start") or "09:00", "HH:mm")
        if t.isValid():
            self.simple_time.setTime(t)
        dur = int(item.get("duration_min") or 0)
        self.simple_hour.setValue(dur // 60)
        self.simple_min.setValue(dur % 60)
        idx = self.simple_priority.findData(item.get("priority") or "medium")
        self.simple_priority.setCurrentIndex(idx if idx >= 0 else 1)
        self.simple_notes.setPlainText(item.get("notes") or "")
        self._recompute_simple()

        is_exp = bool(item.get("is_experiment")) or bool(linked_id)
        self.mode_combo.blockSignals(True)
        self.mode_combo.setCurrentIndex(1 if is_exp else 0)
        self.mode_combo.blockSignals(False)
        if is_exp:
            self.exp_form.load_plan_item(item)
        self._on_mode_changed(copy=False)

    # ------------------------------------------------------------------ 保存

    def _accept(self) -> None:
        if self.mode_combo.currentData() == 1:
            data = self.exp_form.collect()
            title = (data.get("title") or "").strip()
            if not title:
                from PySide6.QtWidgets import QMessageBox

                QMessageBox.warning(self, config.APP_NAME, "请填写实验标题。")
                return
            start = data.get("planned_start") or ""
            planned_date = start[:10] or self.default_date
            planned_start = start[11:16] or "09:00"
            item_data = {
                "week_start": time_utils.monday_of(
                    datetime.strptime(planned_date, "%Y-%m-%d").date()).strftime("%Y-%m-%d"),
                "title": title,
                "type": data.get("type") or "",
                "planned_date": planned_date,
                "planned_start": planned_start,
                "duration_min": int(data.get("duration_min") or 0),
                "priority": data.get("priority") or "medium",
                "notes": data.get("notes") or "",
                "is_experiment": 1,
                "goal": data.get("goal") or "",
                "steps": data.get("steps") or "",
                "tags": data.get("tags") or [],
                "remind_enabled": data.get("remind_enabled") or 0,
                "remind_advance_min": data.get("remind_advance_min") or 0,
                "remind_on_time": data.get("remind_on_time"),
                "remind_end_min": data.get("remind_end_min") or 0,
                "followups": data.get("followups") or [],
            }
        else:
            title = self.simple_title.text().strip()
            if not title:
                from PySide6.QtWidgets import QMessageBox

                QMessageBox.warning(self, config.APP_NAME, "请填写规划项标题。")
                return
            planned_date = self.simple_date.date().toString("yyyy-MM-dd")
            item_data = {
                "week_start": time_utils.monday_of(
                    self.simple_date.date().toPython()).strftime("%Y-%m-%d"),
                "title": title,
                "type": self.simple_type.currentText().strip(),
                "planned_date": planned_date,
                "planned_start": self.simple_time.time().toString("HH:mm"),
                "duration_min": self._duration(),
                "priority": self.simple_priority.currentData(),
                "notes": self.simple_notes.toPlainText(),
                "is_experiment": 0,
            }
        if self.item_id is None:
            self.saved_id = weekly.create_item(item_data)
        else:
            weekly.update_item(self.item_id, item_data)
            self.saved_id = self.item_id
        super().accept()


# ---------------------------------------------------------------------------
# 规划卡片（可拖拽）
# ---------------------------------------------------------------------------
class PlanCard(QFrame):
    def __init__(self, item: dict, on_convert, on_delete, on_edit=None):
        super().__init__()
        self.item = item
        self._on_edit = on_edit
        self._press_pos = None
        self.setObjectName("card")

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        strip = QFrame()
        strip.setFixedWidth(4)
        strip.setStyleSheet(f"background: {_priority_color(item['priority'])}; border: none;")
        lay.addWidget(strip)

        body = QVBoxLayout()
        body.setContentsMargins(10, 10, 10, 10)
        body.setSpacing(6)

        title = QLabel(item["title"])
        title.setWordWrap(True)
        title.setObjectName("cardTitle")

        time_text = f"{item['planned_start'] or '—'} ~ {item['planned_end'] or '—'}"
        if item.get("planned_start") and item.get("planned_end") and item["planned_end"] < item["planned_start"]:
            time_text += "（跨天）"
        time_label = QLabel(time_text)
        time_label.setObjectName("cardTitle")

        meta = QHBoxLayout()
        meta.setSpacing(6)
        dur = time_utils.format_duration(item["duration_min"])
        if dur:
            meta.addWidget(QLabel(dur))
        if item.get("is_experiment"):
            meta.addWidget(badge("实验", "primary"))
        followups = _parse_list(item.get("followups"))
        if followups:
            meta.addWidget(badge(f"跟随 {len(followups)}", "warning"))
        meta.addWidget(badge(_PLAN_STATUS.get(item["status"], item["status"]),
                             _PLAN_STATUS_COLORS.get(item["status"], "subtext")))
        meta.addStretch()

        btns = QHBoxLayout()
        btns.setSpacing(4)
        conv = QPushButton("转实验")
        conv.setCursor(Qt.PointingHandCursor)
        conv.setEnabled(not item["linked_experiment_id"])
        conv.clicked.connect(lambda: on_convert(item["id"]))
        edit = QPushButton("编辑")
        edit.setCursor(Qt.PointingHandCursor)
        edit.clicked.connect(lambda: (on_edit(item["id"]) if on_edit else None))
        dele = QPushButton("删")
        dele.setCursor(Qt.PointingHandCursor)
        dele.clicked.connect(lambda: on_delete(item["id"]))
        btns.addStretch()
        btns.addWidget(conv)
        btns.addWidget(edit)
        btns.addWidget(dele)

        body.addWidget(title)
        body.addWidget(time_label)
        body.addLayout(meta)
        if item["notes"]:
            note = QLabel(item["notes"])
            note.setWordWrap(True)
            note.setObjectName("muted")
            body.addWidget(note)
        body.addLayout(btns)
        lay.addLayout(body, 1)

    def mouseDoubleClickEvent(self, event) -> None:
        if self._on_edit is not None:
            self._on_edit(self.item["id"])
        super().mouseDoubleClickEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._press_pos = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if not (event.buttons() & Qt.LeftButton) or self._press_pos is None:
            return
        if (event.position().toPoint() - self._press_pos).manhattanLength() < QApplication.startDragDistance():
            return
        drag = QDrag(self)
        mime = QMimeData()
        mime.setText(str(self.item["id"]))
        drag.setMimeData(mime)
        # 半透明拖影
        pm = self.grab()
        painter = QPainter(pm)
        painter.setCompositionMode(QPainter.CompositionMode_DestinationIn)
        painter.fillRect(pm.rect(), QColor(0, 0, 0, 170))
        painter.end()
        drag.setPixmap(pm)
        drag.setHotSpot(event.position().toPoint())
        drag.exec(Qt.MoveAction)


# ---------------------------------------------------------------------------
# 天列（接受拖放）
# ---------------------------------------------------------------------------
class DayColumn(QWidget):
    dropped = Signal(int, str, int)  # item_id, date, index

    def __init__(self, date_str: str, on_add):
        super().__init__()
        self.date = date_str
        self.cards: list[PlanCard] = []
        self.setAcceptDrops(True)
        self.setAttribute(Qt.WA_StyledBackground, True)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        head = QHBoxLayout()
        d = datetime.strptime(date_str, "%Y-%m-%d").date()
        title = QLabel(f"{_WEEKDAY_CN[d.weekday()]}")
        title.setObjectName("cardTitle")
        datelbl = QLabel(d.strftime("%m-%d"))
        datelbl.setObjectName("muted")
        self._title_label = title
        self._date_label = datelbl
        self.conflict_dot = QLabel("")
        self.conflict_dot.setStyleSheet("color: #EF4444; font-size: 14px;")
        head.addWidget(title)
        head.addWidget(datelbl)
        head.addWidget(self.conflict_dot)
        head.addStretch()
        lay.addLayout(head)

        self.cards_layout = QVBoxLayout()
        self.cards_layout.setSpacing(8)
        lay.addLayout(self.cards_layout)
        lay.addStretch()

        add_btn = QPushButton("＋ 添加")
        add_btn.setCursor(Qt.PointingHandCursor)
        add_btn.clicked.connect(lambda: on_add(self.date))
        lay.addWidget(add_btn)

    def set_date(self, date_str: str) -> None:
        """切换周时更新这一列的日期与标题。"""
        self.date = date_str
        d = datetime.strptime(date_str, "%Y-%m-%d").date()
        self._title_label.setText(f"{_WEEKDAY_CN[d.weekday()]}")
        self._date_label.setText(d.strftime("%m-%d"))

    def _index_at(self, y: float) -> int:
        for i, card in enumerate(self.cards):
            if y < card.geometry().center().y():
                return i
        return len(self.cards)

    def _highlight(self, on: bool) -> None:
        from .. import theme

        c = theme.current()
        if on:
            self.setStyleSheet(
                f"QWidget {{ border: 2px dashed {c['primary']}; "
                f"background: {c['primary_tint']}; border-radius: 8px; }}"
            )
        else:
            self.setStyleSheet("")

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasText():
            self._highlight(True)
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragLeaveEvent(self, event) -> None:
        self._highlight(False)
        super().dragLeaveEvent(event)

    def dragMoveEvent(self, event) -> None:
        if event.mimeData().hasText():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        self._highlight(False)
        item_id = int(event.mimeData().text())
        self.dropped.emit(item_id, self.date, self._index_at(event.position().y()))
        event.acceptProposedAction()


class DropZone(QFrame):
    """顶部“上一周 / 下一周”投放区，用于跨周移动。"""

    dropped = Signal(int, int)  # item_id, delta_days

    def __init__(self, text: str, delta_days: int):
        super().__init__()
        self._delta = delta_days
        self.setAcceptDrops(True)
        self.setObjectName("card")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 6, 12, 6)
        lbl = QLabel(text)
        lbl.setObjectName("muted")
        lay.addWidget(lbl)

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasText():
            event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:
        if event.mimeData().hasText():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        item_id = int(event.mimeData().text())
        self.dropped.emit(item_id, self._delta)
        event.acceptProposedAction()


# ---------------------------------------------------------------------------
# 规划页
# ---------------------------------------------------------------------------
class PlannerPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        today_monday = time_utils.monday_of(date.today())
        self.week_start = (today_monday + timedelta(days=7)).strftime("%Y-%m-%d")
        self._items: list[dict] = []
        self._columns: dict[str, DayColumn] = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 24, 28, 24)
        outer.setSpacing(12)

        # 顶栏
        top = QHBoxLayout()
        top.setSpacing(8)
        title = QLabel("实验规划")
        title.setObjectName("pageTitle")
        self.prev_btn = QPushButton("◀ 上一周")
        self.next_btn = QPushButton("下一周 ▶")
        self.today_btn = QPushButton("回到本周")
        for b in (self.prev_btn, self.next_btn, self.today_btn):
            b.setCursor(Qt.PointingHandCursor)
        self.prev_btn.clicked.connect(lambda: self._shift_week(-7))
        self.next_btn.clicked.connect(lambda: self._shift_week(7))
        self.today_btn.clicked.connect(lambda: self._shift_week(0, follow_today=True))
        self.week_label = QLabel()
        self.week_label.setObjectName("cardTitle")
        copy_btn = QPushButton("从上周复制")
        copy_btn.setCursor(Qt.PointingHandCursor)
        copy_btn.clicked.connect(self._copy_prev_week)
        tpl_btn = QPushButton("从模板创建")
        tpl_btn.setCursor(Qt.PointingHandCursor)
        tpl_btn.clicked.connect(self._from_template)

        top.addWidget(title)
        top.addSpacing(8)
        top.addWidget(self.prev_btn)
        top.addWidget(self.week_label)
        top.addWidget(self.next_btn)
        top.addWidget(self.today_btn)
        top.addStretch()
        top.addWidget(copy_btn)
        top.addWidget(tpl_btn)
        outer.addLayout(top)

        # 跨周投放区
        drop_row = QHBoxLayout()
        drop_row.setSpacing(8)
        self.drop_prev = DropZone("拖到这里：移到上一周", -7)
        self.drop_next = DropZone("拖到这里：移到下一周", 7)
        self.drop_prev.dropped.connect(self._on_week_drop)
        self.drop_next.dropped.connect(self._on_week_drop)
        drop_row.addWidget(self.drop_prev)
        drop_row.addWidget(self.drop_next)
        drop_row.addStretch()
        outer.addLayout(drop_row)

        # 七列（固定等宽格子，每列独立纵向滚动，禁止横向滚动）
        self.columns_layout = QHBoxLayout()
        self.columns_layout.setContentsMargins(0, 0, 0, 0)
        self.columns_layout.setSpacing(10)
        monday = datetime.strptime(self.week_start, "%Y-%m-%d").date()
        for i in range(7):
            d = (monday + timedelta(days=i)).strftime("%Y-%m-%d")
            col = DayColumn(d, self._add_item)
            col.dropped.connect(self._on_drop)
            self._columns[d] = col
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QScrollArea.NoFrame)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            scroll.setWidget(col)
            self.columns_layout.addWidget(scroll, 1)
        outer.addLayout(self.columns_layout, 1)

        # 底部统计
        self.footer = Card()
        fl = QHBoxLayout(self.footer)
        fl.setContentsMargins(20, 12, 20, 12)
        fl.setSpacing(10)
        self.total_label = QLabel()
        self.total_label.setObjectName("cardTitle")
        self.conflict_label = QLabel("")
        self.conflict_label.setObjectName("muted")
        fl.addWidget(self.total_label)
        fl.addStretch()
        fl.addWidget(self.conflict_label)
        outer.addWidget(self.footer)

        self.refresh()

    # ------------------------------------------------------------------ 行为

    def _shift_week(self, delta_days: int, follow_today: bool = False) -> None:
        if follow_today:
            self.week_start = time_utils.monday_of(date.today()).strftime("%Y-%m-%d")
        else:
            self.week_start = (
                datetime.strptime(self.week_start, "%Y-%m-%d") + timedelta(days=delta_days)
            ).strftime("%Y-%m-%d")
        self.refresh()

    def _add_item(self, date_str: str) -> None:
        dlg = PlanItemDialog(date_str, self)
        if dlg.exec() == QDialog.Accepted:
            self.refresh()

    def _edit_item(self, item_id: int) -> None:
        dlg = PlanItemDialog(self.week_start, self, item_id=item_id)
        if dlg.exec() == QDialog.Accepted:
            self.refresh()

    def _copy_prev_week(self) -> None:
        prev = (datetime.strptime(self.week_start, "%Y-%m-%d") - timedelta(days=7)).strftime("%Y-%m-%d")
        weekly.copy_week(prev, self.week_start)
        self.refresh()

    def _from_template(self) -> None:
        weekly.create_from_template(self.week_start)
        self.refresh()

    def _on_drop(self, item_id: int, date_str: str, index: int) -> None:
        target = [it for it in self._items if it["planned_date"] == date_str and it["id"] != item_id]
        target.sort(key=lambda x: x["sort_order"])
        ids = [it["id"] for it in target]
        ids.insert(min(index, len(ids)), item_id)
        weekly.set_item_date_order(item_id, date_str, 0)
        weekly.reorder_date(date_str, ids)
        self.refresh()

    def _on_week_drop(self, item_id: int, delta_days: int) -> None:
        item = weekly.get_item(item_id)
        if item is None:
            return
        new_date = (datetime.strptime(item["planned_date"], "%Y-%m-%d") + timedelta(days=delta_days)).strftime("%Y-%m-%d")
        weekly.set_item_date_order(item_id, new_date, 9999)
        self.refresh()

    def _convert(self, item_id: int) -> None:
        exp_id = weekly.convert_to_experiment(item_id)
        if exp_id:
            self.refresh()

    def _delete_item(self, item_id: int) -> None:
        from PySide6.QtWidgets import QMessageBox

        if QMessageBox.question(self, config.APP_NAME, "删除这个规划项？") == QMessageBox.Yes:
            weekly.delete_item(item_id)
            self.refresh()

    def refresh(self) -> None:
        monday = self.week_start
        sunday = (datetime.strptime(monday, "%Y-%m-%d") + timedelta(days=6)).strftime("%Y-%m-%d")
        iso = datetime.strptime(monday, "%Y-%m-%d").date().isocalendar()
        self.week_label.setText(f"{iso[0]}年 第{iso[1]}周  {monday[5:]} ~ {sunday[5:]}")

        # 切换周后更新每列日期（周一~周日）
        monday_date = datetime.strptime(monday, "%Y-%m-%d").date()
        new_cols = {}
        for i, col in enumerate(self._columns.values()):
            d = (monday_date + timedelta(days=i)).strftime("%Y-%m-%d")
            col.set_date(d)
            new_cols[d] = col
        self._columns = new_cols

        self._items = weekly.list_items_range(monday, sunday)
        totals = weekly.week_totals(self._items)

        # 清空各列卡片
        for col in self._columns.values():
            for card in col.cards:
                col.cards_layout.removeWidget(card)
                card.deleteLater()
            col.cards.clear()

        # 填充卡片
        by_date: dict[str, list[dict]] = {}
        for it in self._items:
            by_date.setdefault(it["planned_date"], []).append(it)
        for date_str, col in self._columns.items():
            for it in sorted(by_date.get(date_str, []),
                             key=lambda x: (x.get("planned_start") or "99:99", x["sort_order"])):
                card = PlanCard(it, self._convert, self._delete_item, self._edit_item)
                col.cards_layout.addWidget(card)
                col.cards.append(card)
            col.conflict_dot.setText("●" if date_str in totals["conflicts"] else "")

        # 底部统计
        total_h = totals["total_min"] / 60
        self.total_label.setText(f"本周预计总时长：{total_h:.1f} 小时（{len(self._items)} 项）")
        if totals["conflicts"]:
            days = "、".join(sorted(d[5:] for d in totals["conflicts"]))
            self.conflict_label.setText(f"⚠ 时间冲突：{days}")
        else:
            self.conflict_label.setText("")

    def on_theme_changed(self) -> None:
        self.refresh()

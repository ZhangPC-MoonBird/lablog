"""实验规划页：下周七天视图 + 拖拽排序/跨天/跨周 + 一键转实验。

- 默认显示下一周
- 卡片拖拽（QDrag）：同周内跨天移动 + 列内排序；拖到顶部“上一周/下一周”投放区跨周移动
- 拖拽落点按 y 坐标计算插入位置，落定后重排 sort_order 并持久化
- 底部统计周总时长、每日数量/时长，冲突红点提示
"""
from __future__ import annotations

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

_PLAN_STATUS = {"planned": "未开始", "converted": "已转实验", "done": "已完成", "cancelled": "已取消"}
_PLAN_STATUS_COLORS = {"planned": "subtext", "converted": "primary", "done": "success", "cancelled": "subtext"}
_WEEKDAY_CN = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")


def _priority_color(key: str) -> str:
    from .. import theme

    return theme.current().get(exp_model.PRIORITY_COLORS.get(key, "subtext"), "#9CA3AF")


# ---------------------------------------------------------------------------
# 快速添加弹窗
# ---------------------------------------------------------------------------
class PlanItemDialog(QDialog):
    def __init__(self, default_date: str, parent=None):
        super().__init__(parent)
        self.saved_id: int | None = None
        self.setWindowTitle("添加规划项")
        self.setMinimumWidth(460)

        form = QVBoxLayout(self)
        form.setContentsMargins(22, 18, 22, 18)
        form.setSpacing(10)

        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("标题（必填）")

        self.type_combo = QComboBox()
        self.type_combo.setEditable(True)
        self.type_combo.addItem("")
        for t in exp_model.all_types():
            self.type_combo.addItem(t)

        d = datetime.strptime(default_date, "%Y-%m-%d").date()
        self.date_edit = QDateEdit(QDate(d.year, d.month, d.day))
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("yyyy-MM-dd")

        self.time_edit = QTimeEdit(QTime(9, 0))
        self.time_edit.setDisplayFormat("HH:mm")

        self.hour_spin = QSpinBox()
        self.hour_spin.setRange(0, 24)
        self.hour_spin.setSuffix(" 小时")
        self.min_spin = QSpinBox()
        self.min_spin.setRange(0, 59)
        self.min_spin.setSuffix(" 分钟")

        self.end_label = QLabel("—")
        self.end_label.setObjectName("cardTitle")

        self.priority_combo = QComboBox()
        for k, v in exp_model.PRIORITY_LABELS.items():
            self.priority_combo.addItem(v, k)
        self.priority_combo.setCurrentIndex(1)

        self.notes_edit = QPlainTextEdit()
        self.notes_edit.setFixedHeight(64)
        self.notes_edit.setPlaceholderText("备注")

        # 行式布局
        def row(lbl, *widgets):
            h = QHBoxLayout()
            h.setSpacing(8)
            l = QLabel(lbl)
            l.setMinimumWidth(60)
            h.addWidget(l)
            for w in widgets:
                h.addWidget(w)
            h.addStretch()
            return h

        form.addLayout(row("标题", self.title_edit))
        form.addLayout(row("类型", self.type_combo))
        form.addLayout(row("日期", self.date_edit))
        form.addLayout(row("开始时间", self.time_edit))
        form.addLayout(row("预计耗时", self.hour_spin, self.min_spin))
        form.addLayout(row("预计结束", self.end_label))
        form.addLayout(row("优先级", self.priority_combo))
        form.addWidget(QLabel("备注"))
        form.addWidget(self.notes_edit)

        btns = QHBoxLayout()
        btns.addStretch()
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        save = QPushButton("添加")
        save.setDefault(True)
        save.clicked.connect(self._accept)
        btns.addWidget(cancel)
        btns.addWidget(save)
        form.addLayout(btns)

        self.date_edit.dateChanged.connect(lambda *_: self._recompute())
        self.time_edit.timeChanged.connect(lambda *_: self._recompute())
        self.hour_spin.valueChanged.connect(lambda *_: self._recompute())
        self.min_spin.valueChanged.connect(lambda *_: self._recompute())
        self._recompute()

    def _duration(self) -> int:
        return self.hour_spin.value() * 60 + self.min_spin.value()

    def _recompute(self) -> None:
        start = self.time_edit.time().toString("HH:mm")
        dur = self._duration()
        if dur > 0:
            end = time_utils.minutes_to_time(time_utils.time_to_minutes(start) + dur)
            self.end_label.setText(f"{end}（跨天）" if end < start else end)
        else:
            self.end_label.setText("—")

    def _accept(self) -> None:
        if not self.title_edit.text().strip():
            return
        self.saved_id = weekly.create_item({
            "week_start": time_utils.monday_of(
                self.date_edit.date().toPython()).strftime("%Y-%m-%d"),
            "title": self.title_edit.text().strip(),
            "type": self.type_combo.currentText().strip(),
            "planned_date": self.date_edit.date().toString("yyyy-MM-dd"),
            "planned_start": self.time_edit.time().toString("HH:mm"),
            "duration_min": self._duration(),
            "priority": self.priority_combo.currentData(),
            "notes": self.notes_edit.toPlainText(),
        })
        super().accept()


# ---------------------------------------------------------------------------
# 规划卡片（可拖拽）
# ---------------------------------------------------------------------------
class PlanCard(QFrame):
    def __init__(self, item: dict, on_convert, on_delete):
        super().__init__()
        self.item = item
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

        time_label = QLabel(f"{item['planned_start'] or '—'} ~ {item['planned_end'] or '—'}")
        time_label.setObjectName("cardTitle")

        meta = QHBoxLayout()
        meta.setSpacing(6)
        dur = time_utils.format_duration(item["duration_min"])
        if dur:
            meta.addWidget(QLabel(dur))
        meta.addWidget(badge(_PLAN_STATUS.get(item["status"], item["status"]),
                             _PLAN_STATUS_COLORS.get(item["status"], "subtext")))
        meta.addStretch()

        btns = QHBoxLayout()
        btns.setSpacing(4)
        conv = QPushButton("转实验")
        conv.setCursor(Qt.PointingHandCursor)
        conv.setEnabled(not item["linked_experiment_id"])
        conv.clicked.connect(lambda: on_convert(item["id"]))
        dele = QPushButton("删")
        dele.setCursor(Qt.PointingHandCursor)
        dele.clicked.connect(lambda: on_delete(item["id"]))
        btns.addStretch()
        btns.addWidget(conv)
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
                card = PlanCard(it, self._convert, self._delete_item)
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

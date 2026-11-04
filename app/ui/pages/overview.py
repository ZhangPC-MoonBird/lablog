"""实验总览页：按日期汇总所有实验、计划/实际时间、状态与跟随关系。

- 顶部统计：实验总数 / 已完成 / 进行中 / 累计耗时
- 筛选：全部/本周/本月/近30天/今年、类型、状态、主实验/跟随实验、关键词
- 时间线：按“实际开始 → 计划开始 → 创建时间”分组，日期倒序
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ...models import experiment
from ...utils import time_utils
from ..components import EmptyState, StatCard, badge


class _OverviewRow(QFrame):
    """总览里的一条实验记录（整行可点击进入详情）。"""

    clicked = Signal(int)

    def __init__(self, exp: dict):
        super().__init__()
        self.exp_id = int(exp["id"])
        self.setObjectName("card")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setCursor(Qt.PointingHandCursor)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(14)

        time_col = QVBoxLayout()
        time_col.setSpacing(1)
        start = exp.get("actual_start") or exp.get("planned_start") or ""
        clock = QLabel(start[11:16] if start else "—")
        clock.setObjectName("statValue")
        clock.setStyleSheet("font-size: 18px;")
        dur = self._duration_text(exp)
        dur_lbl = QLabel(dur or "—")
        dur_lbl.setObjectName("muted")
        time_col.addWidget(clock)
        time_col.addWidget(dur_lbl)
        lay.addLayout(time_col)

        body = QVBoxLayout()
        body.setSpacing(3)
        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        title = QLabel(exp["title"])
        title.setObjectName("cardTitle")
        title.setWordWrap(True)
        title_row.addWidget(title)
        if exp.get("parent_id"):
            title_row.addWidget(badge("跟随", "warning"))
        count = int(exp.get("followup_count") or 0)
        if count:
            title_row.addWidget(badge(f"{count} 条跟随", "primary"))
        title_row.addStretch()
        body.addLayout(title_row)

        meta_parts = []
        if exp.get("type"):
            meta_parts.append(exp["type"])
        tags = experiment.tags_to_str(exp)
        if tags:
            meta_parts.append(tags)
        if exp.get("parent_title"):
            meta_parts.append(f"跟随自：{exp['parent_title']}")
        meta = QLabel(" · ".join(meta_parts) or "未分类")
        meta.setObjectName("muted")
        meta.setWordWrap(True)
        body.addWidget(meta)

        time_detail = QLabel(self._time_detail(exp))
        time_detail.setObjectName("muted")
        time_detail.setWordWrap(True)
        body.addWidget(time_detail)
        lay.addLayout(body, 1)

        right = QVBoxLayout()
        right.setSpacing(4)
        status = badge(
            experiment.STATUS_LABELS.get(exp["status"], exp["status"]),
            experiment.STATUS_COLORS.get(exp["status"], "subtext"))
        priority = badge(
            experiment.PRIORITY_LABELS.get(exp["priority"], "中"),
            experiment.PRIORITY_COLORS.get(exp["priority"], "subtext"))
        right.addWidget(status, 0, Qt.AlignRight)
        right.addWidget(priority, 0, Qt.AlignRight)
        lay.addLayout(right)

    @staticmethod
    def _duration_text(exp: dict) -> str:
        if exp.get("actual_start") and exp.get("actual_end"):
            try:
                a = datetime.strptime(exp["actual_start"], "%Y-%m-%d %H:%M:%S")
                b = datetime.strptime(exp["actual_end"], "%Y-%m-%d %H:%M:%S")
                return time_utils.format_duration(int((b - a).total_seconds() // 60)) + "（实际）"
            except ValueError:
                pass
        return time_utils.format_duration(exp.get("duration_min") or 0)

    @staticmethod
    def _time_detail(exp: dict) -> str:
        plan = exp.get("planned_start") or ""
        if plan:
            text = f"计划：{plan} ~ {exp.get('planned_end') or '—'}"
        else:
            text = "计划：未安排时间"
        if exp.get("actual_start"):
            actual = f"实际：{exp['actual_start'][:16]}"
            actual += f" ~ {exp['actual_end'][:16]}" if exp.get("actual_end") else "（进行中）"
            text += f"　·　{actual}"
        return text

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.exp_id)
        super().mousePressEvent(event)


class OverviewPage(QWidget):
    open_experiment = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._exps: list[dict] = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 24, 28, 24)
        outer.setSpacing(14)

        title = QLabel("实验总览")
        title.setObjectName("pageTitle")
        sub = QLabel("所有实验与时间 · 计划 / 实际 / 跟随实验")
        sub.setObjectName("muted")
        outer.addWidget(title)
        outer.addWidget(sub)

        stats = QHBoxLayout()
        stats.setSpacing(14)
        self.stat_total = StatCard("实验总数")
        self.stat_done = StatCard("已完成")
        self.stat_running = StatCard("进行中")
        self.stat_hours = StatCard("累计实验时长")
        for w in (self.stat_total, self.stat_done, self.stat_running, self.stat_hours):
            stats.addWidget(w, 1)
        outer.addLayout(stats)

        filters = QHBoxLayout()
        filters.setSpacing(8)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("搜索标题 / 目标 / 备注…")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.setFixedWidth(210)
        self.range_combo = QComboBox()
        for key, label in (
            ("all", "全部时间"), ("week", "本周"), ("month", "本月"),
            ("30d", "近30天"), ("year", "今年"),
        ):
            self.range_combo.addItem(label, key)
        self.type_combo = QComboBox()
        self.type_combo.setMinimumWidth(110)
        self.status_combo = QComboBox()
        self.status_combo.setMinimumWidth(100)
        self.follow_combo = QComboBox()
        self.follow_combo.addItem("全部实验", "all")
        self.follow_combo.addItem("仅主实验", "main")
        self.follow_combo.addItem("仅跟随实验", "followup")
        for w in (self.search_edit, self.range_combo, self.type_combo,
                  self.status_combo, self.follow_combo):
            filters.addWidget(w)
        filters.addStretch()
        self.summary_label = QLabel("")
        self.summary_label.setObjectName("muted")
        filters.addWidget(self.summary_label)
        outer.addLayout(filters)

        self.stack = QStackedWidget()
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.NoFrame)
        self.list_host = QWidget()
        self.list_layout = QVBoxLayout(self.list_host)
        self.list_layout.setContentsMargins(0, 0, 6, 0)
        self.list_layout.setSpacing(8)
        self.list_layout.addStretch()
        self.scroll.setWidget(self.list_host)
        self.stack.addWidget(self.scroll)
        self.empty = EmptyState(
            "还没有实验记录", "在「实验内容」新建实验，或从「实验规划」一键转实验后，这里会按时间汇总")
        self.stack.addWidget(self.empty)
        outer.addWidget(self.stack, 1)

        self.search_edit.textChanged.connect(self.refresh)
        self.range_combo.currentIndexChanged.connect(self.refresh)
        self.type_combo.currentIndexChanged.connect(self.refresh)
        self.status_combo.currentIndexChanged.connect(self.refresh)
        self.follow_combo.currentIndexChanged.connect(self.refresh)

        self.refresh()

    # ------------------------------------------------------------------ 刷新

    def refresh(self) -> None:
        self._rebuild_filters()
        start, end = self._range_bounds()
        self._exps = experiment.list_for_overview(
            status=self.status_combo.currentData(),
            type_=self.type_combo.currentData(),
            keyword=self.search_edit.text(),
            start_date=start,
            end_date=end,
        )
        self._rebuild_stats()
        self._rebuild_list()
        self.stack.setCurrentIndex(0 if self._exps else 1)

    def _rebuild_filters(self) -> None:
        cur_type = self.type_combo.currentData()
        self.type_combo.blockSignals(True)
        self.type_combo.clear()
        self.type_combo.addItem("全部类型", "all")
        for t in experiment.all_types():
            self.type_combo.addItem(t, t)
        idx = self.type_combo.findData(cur_type)
        self.type_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.type_combo.blockSignals(False)

        cur_status = self.status_combo.currentData()
        self.status_combo.blockSignals(True)
        self.status_combo.clear()
        self.status_combo.addItem("全部状态", "all")
        for s, label in experiment.STATUS_LABELS.items():
            self.status_combo.addItem(label, s)
        idx = self.status_combo.findData(cur_status)
        self.status_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.status_combo.blockSignals(False)

    def _range_bounds(self) -> tuple[str | None, str | None]:
        key = self.range_combo.currentData()
        today = date.today()
        if key == "week":
            start = time_utils.monday_of(today)
            end = start + timedelta(days=6)
        elif key == "month":
            start = today.replace(day=1)
            next_month = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
            end = next_month - timedelta(days=1)
        elif key == "30d":
            start, end = today - timedelta(days=29), today
        elif key == "year":
            start, end = date(today.year, 1, 1), date(today.year, 12, 31)
        else:
            return None, None
        return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")

    def _rebuild_stats(self) -> None:
        total = len(self._exps)
        done = sum(1 for e in self._exps if e["status"] == "done")
        running = sum(1 for e in self._exps if e["status"] == "running")
        minutes = 0
        for e in self._exps:
            if e.get("actual_start") and e.get("actual_end"):
                try:
                    a = datetime.strptime(e["actual_start"], "%Y-%m-%d %H:%M:%S")
                    b = datetime.strptime(e["actual_end"], "%Y-%m-%d %H:%M:%S")
                    minutes += max(0, int((b - a).total_seconds() // 60))
                    continue
                except ValueError:
                    pass
            minutes += int(e.get("duration_min") or 0)
        self.stat_total.set_value(total)
        self.stat_done.set_value(done)
        self.stat_running.set_value(running)
        self.stat_hours.set_value(time_utils.format_duration(minutes) or "0分")
        self.summary_label.setText(f"当前筛选：{total} 个实验")

    def _rebuild_list(self) -> None:
        while self.list_layout.count() > 1:
            item = self.list_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        groups: dict[str, list[dict]] = {}
        for e in self._exps:
            groups.setdefault(e.get("overview_date") or "未知日期", []).append(e)

        insert_at = 0
        for day in sorted(groups.keys(), reverse=True):
            exps = groups[day]
            header = QLabel(self._group_header(day, exps))
            header.setObjectName("sectionHeader")
            self.list_layout.insertWidget(insert_at, header)
            insert_at += 1
            for e in exps:
                row = _OverviewRow(e)
                row.clicked.connect(self.open_experiment.emit)
                self.list_layout.insertWidget(insert_at, row)
                insert_at += 1

    @staticmethod
    def _group_header(day: str, exps: list[dict]) -> str:
        try:
            d = datetime.strptime(day, "%Y-%m-%d")
            label = f"{day}  {time_utils.cn_weekday(d)}"
        except ValueError:
            label = day
        minutes = 0
        for e in exps:
            if e.get("actual_start") and e.get("actual_end"):
                try:
                    a = datetime.strptime(e["actual_start"], "%Y-%m-%d %H:%M:%S")
                    b = datetime.strptime(e["actual_end"], "%Y-%m-%d %H:%M:%S")
                    minutes += max(0, int((b - a).total_seconds() // 60))
                    continue
                except ValueError:
                    pass
            minutes += int(e.get("duration_min") or 0)
        return f"{label}　·　{len(exps)} 个实验　·　{time_utils.format_duration(minutes) or '0分'}"

    def on_theme_changed(self) -> None:
        self.empty.on_theme_changed()
        self.refresh()

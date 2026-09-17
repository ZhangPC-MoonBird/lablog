"""仪表盘：今日概览 + 今日实验内容。

- 统计卡：今日实验 / 进行中 / 本周已完成 / 待提醒
- 今日实验内容：今天计划的实验列表（时间、标题、状态）
"""
from __future__ import annotations

from datetime import datetime, timedelta

from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from ...database import fetch_all, fetch_one
from ...models import experiment
from ...utils import time_utils
from ..components import Card, StatCard, badge


class DashboardPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 24, 28, 24)
        outer.setSpacing(16)

        title = QLabel("仪表盘")
        title.setObjectName("pageTitle")
        sub = QLabel("今日概览 · 今日实验 · 提醒")
        sub.setObjectName("muted")
        outer.addWidget(title)
        outer.addWidget(sub)
        outer.addSpacing(4)

        stats = QHBoxLayout()
        stats.setSpacing(16)
        self.stat_today = StatCard("今日实验")
        self.stat_running = StatCard("进行中")
        self.stat_done_week = StatCard("本周已完成")
        self.stat_remind = StatCard("待提醒")
        for w in (self.stat_today, self.stat_running, self.stat_done_week, self.stat_remind):
            stats.addWidget(w, 1)
        outer.addLayout(stats)

        body = QHBoxLayout()
        body.setSpacing(16)

        # 今日实验内容
        self.today_card = Card()
        tc = QVBoxLayout(self.today_card)
        tc.setContentsMargins(24, 20, 24, 16)
        tc.setSpacing(10)
        self.today_title = QLabel()
        self.today_title.setObjectName("cardTitle")
        tc.addWidget(self.today_title)
        self.today_list = QVBoxLayout()
        self.today_list.setSpacing(2)
        tc.addLayout(self.today_list)
        tc.addStretch()
        body.addWidget(self.today_card, 2)

        # 本周进度占位
        info_card = Card()
        ic = QVBoxLayout(info_card)
        ic.setContentsMargins(24, 20, 24, 20)
        ic.setSpacing(8)
        it = QLabel("本周进度")
        it.setObjectName("cardTitle")
        ip = QLabel("本周完成进度环与超时提示将在后续接入。")
        ip.setObjectName("muted")
        ip.setWordWrap(True)
        ic.addWidget(it)
        ic.addWidget(ip)
        ic.addStretch()
        body.addWidget(info_card, 1)
        outer.addLayout(body, 1)

        self.refresh()

    # ------------------------------------------------------------------ 刷新

    def refresh(self) -> None:
        """刷新统计数字与今日实验列表。"""
        today = datetime.now().strftime("%Y-%m-%d")
        monday = (datetime.now() - timedelta(days=datetime.now().weekday())).strftime(
            "%Y-%m-%d"
        )
        self.today_title.setText(f"今日实验内容 · {time_utils.format_date_cn(datetime.now())}")
        self.stat_today.set_value(
            fetch_one(
                "SELECT COUNT(*) c FROM experiments WHERE substr(planned_start,1,10) = ?",
                (today,),
            )["c"]
        )
        self.stat_running.set_value(
            fetch_one("SELECT COUNT(*) c FROM experiments WHERE status = 'running'")["c"]
        )
        self.stat_done_week.set_value(
            fetch_one(
                "SELECT COUNT(*) c FROM experiments "
                "WHERE status = 'done' AND planned_start >= ?",
                (monday,),
            )["c"]
        )
        self.stat_remind.set_value(
            fetch_one(
                "SELECT COUNT(*) c FROM experiments "
                "WHERE remind_enabled = 1 AND status IN ('planned','running') "
                "AND planned_start >= ?",
                (today,),
            )["c"]
        )
        self._reload_today_experiments(today)

    def _reload_today_experiments(self, today: str) -> None:
        while self.today_list.count():
            item = self.today_list.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        exps = fetch_all(
            "SELECT * FROM experiments WHERE substr(planned_start,1,10) = ? "
            "ORDER BY planned_start",
            (today,),
        )
        if not exps:
            empty = QLabel("今天暂无实验")
            empty.setObjectName("muted")
            self.today_list.addWidget(empty)
            return
        for e in exps:
            self.today_list.addWidget(self._exp_row(e))

    def _exp_row(self, e: dict) -> QWidget:
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 4, 0, 4)
        h.setSpacing(10)
        time_label = QLabel((e["planned_start"] or "—")[11:16])
        time_label.setObjectName("cardTitle")
        h.addWidget(time_label)
        title = QLabel(e["title"])
        title.setWordWrap(True)
        h.addWidget(title, 1)
        h.addWidget(badge(
            experiment.STATUS_LABELS.get(e["status"], e["status"]),
            experiment.STATUS_COLORS.get(e["status"], "subtext")))
        return row

    def on_theme_changed(self) -> None:
        self.refresh()

"""仪表盘：今日概览 + 每日记录编辑区。

- 统计卡：今日实验 / 进行中 / 本周已完成 / 待提醒
- 今日记录：对应 daily_logs 表，编辑后 0.8 秒防抖自动保存；跨日时重载为新一天的记录
"""
from __future__ import annotations

from datetime import datetime, timedelta

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from ...database import fetch_one
from ...models import daily_log
from ...utils import time_utils
from ..components import Card, StatCard, make_expand_button


class DashboardPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._log_date: str = ""

        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 24, 28, 24)
        outer.setSpacing(16)

        title = QLabel("仪表盘")
        title.setObjectName("pageTitle")
        sub = QLabel("今日概览 · 每日记录 · 提醒")
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

        # 今日记录编辑区
        self.today_card = Card()
        tc = QVBoxLayout(self.today_card)
        tc.setContentsMargins(24, 20, 24, 16)
        tc.setSpacing(8)
        self.daily_edit = QPlainTextEdit()
        self.daily_edit.setPlaceholderText("记录今天的工作、进展、问题…（支持 Markdown）")
        self.daily_edit.textChanged.connect(self._on_daily_changed)

        head = QHBoxLayout()
        self.today_title = QLabel()
        self.today_title.setObjectName("cardTitle")
        self.daily_save_label = QLabel("")
        self.daily_save_label.setObjectName("muted")
        head.addWidget(self.today_title)
        head.addStretch()
        head.addWidget(self.daily_save_label)
        head.addWidget(make_expand_button(self.daily_edit, "今日记录"))
        tc.addLayout(head)
        tc.addWidget(self.daily_edit, 1)

        # 防抖自动保存（0.8 秒）
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.timeout.connect(self._save_daily_now)
        body.addWidget(self.today_card, 2)

        # 本周进度占位（M4）
        info_card = Card()
        ic = QVBoxLayout(info_card)
        ic.setContentsMargins(24, 20, 24, 20)
        ic.setSpacing(8)
        it = QLabel("本周进度")
        it.setObjectName("cardTitle")
        ip = QLabel("本周完成进度环与超时提示将在 M4（周整理）接入。")
        ip.setObjectName("muted")
        ip.setWordWrap(True)
        ic.addWidget(it)
        ic.addWidget(ip)
        ic.addStretch()
        body.addWidget(info_card, 1)
        outer.addLayout(body, 1)

        self._load_daily_log()
        self.refresh()

    # ------------------------------------------------------------------ 每日记录

    def _on_daily_changed(self) -> None:
        self.daily_save_label.setText("编辑中…")
        self._save_timer.start(800)

    def _save_daily_now(self) -> None:
        if not self._log_date:
            return
        daily_log.save_content(self._log_date, self.daily_edit.toPlainText())
        self.daily_save_label.setText(f"已保存 {datetime.now().strftime('%H:%M')}")

    def _load_daily_log(self) -> None:
        """加载（或创建）今日记录到编辑器。"""
        self._log_date = datetime.now().strftime("%Y-%m-%d")
        log = daily_log.get_or_create(self._log_date)
        self.daily_edit.blockSignals(True)
        self.daily_edit.setPlainText(log["content"] or "")
        self.daily_edit.blockSignals(False)
        self.today_title.setText(f"今日记录 · {time_utils.format_date_cn(datetime.now())}")
        self.daily_save_label.setText("")

    # ------------------------------------------------------------------ 刷新

    def refresh(self) -> None:
        """刷新统计数字；仅当日期变化时才重载每日记录（不打断编辑）。"""
        today = datetime.now().strftime("%Y-%m-%d")
        monday = (datetime.now() - timedelta(days=datetime.now().weekday())).strftime(
            "%Y-%m-%d"
        )
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
        if self._log_date != today:
            self._load_daily_log()

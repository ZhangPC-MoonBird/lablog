"""提醒服务：每 30 秒扫描一次实验，触发提前/到点/结束提醒。

- 提前提醒（advance）：开始前 N 分钟，只触发一次
- 到点提醒（on_time）：到点后触发；未确认则每 60 秒重复响，直到用户确认
- 结束提醒（end）：结束前 N 分钟，只触发一次

可靠性：reminder_log 带 UNIQUE(experiment_id, remind_type) 去重；
到点提醒用 confirmed 字段判断是否需要重复。
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from PySide6.QtCore import QObject, QTimer, Signal

from ..database import db, execute, fetch_all, fetch_one, get_setting

log = logging.getLogger(__name__)

SCAN_INTERVAL_MS = 5_000  # 每 5 秒扫描一次，保证到点提醒与重复响铃及时
REPEAT_INTERVAL_SEC = 5  # 到点未确认时的重复响铃间隔


class ReminderService(QObject):
    """扫描到期实验并发出提醒信号。"""

    fired = Signal(dict)  # {experiment_id, title, kind, message, planned_start}

    def __init__(self, parent=None):
        super().__init__(parent)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.check)
        self._timer.start(SCAN_INTERVAL_MS)

    def check(self) -> None:
        """立即扫描一次（定时器每 30 秒调用，测试可手动调用）。"""
        now = datetime.now()
        rows = fetch_all(
            "SELECT * FROM experiments WHERE remind_enabled = 1 "
            "AND status IN ('planned','running') "
            "AND planned_start IS NOT NULL AND planned_start != ''"
        )
        for exp in rows:
            self._check_one(exp, now)

    def _check_one(self, exp: dict, now: datetime) -> None:
        try:
            planned = datetime.strptime(exp["planned_start"], "%Y-%m-%d %H:%M")
        except (ValueError, TypeError):
            return

        advance_min = int(exp.get("remind_advance_min") or 0)
        on_time = bool(exp.get("remind_on_time"))
        end_min = int(exp.get("remind_end_min") or 0)
        advance_time = planned - timedelta(minutes=advance_min)

        # 提前提醒：只在实际开始前触发一次
        if advance_min > 0 and advance_time <= now < planned:
            self._fire_once(exp, "advance", f"提前 {advance_min} 分钟提醒", now)

        # 到点提醒：到点后触发，未确认则重复响
        if on_time and planned <= now:
            self._fire_on_time_repeat(exp, now)

        # 结束提醒：结束前 N 分钟触发一次
        if end_min > 0 and exp.get("planned_end"):
            try:
                end = datetime.strptime(exp["planned_end"], "%Y-%m-%d %H:%M")
            except (ValueError, TypeError):
                end = None
            if end and (end - timedelta(minutes=end_min)) <= now < end:
                self._fire_once(exp, "end", f"距结束还有 {end_min} 分钟", now)

    def _fire_once(self, exp: dict, kind: str, message: str, now: datetime) -> None:
        if not self._mark(exp["id"], kind):
            return
        self._emit(exp, kind, message, now)

    def _fire_on_time_repeat(self, exp: dict, now: datetime) -> None:
        log_row = fetch_one(
            "SELECT * FROM reminder_log WHERE experiment_id = ? AND remind_type = 'on_time'",
            (exp["id"],),
        )
        if log_row is None:
            if self._mark(exp["id"], "on_time"):
                self._emit(exp, "on_time", "到点提醒", now)
            return
        if log_row["confirmed"]:
            return
        # 未确认：按用户设置的间隔重复响
        interval = int(get_setting("remind_repeat_interval_sec", 5) or 5)
        try:
            last = datetime.strptime(log_row["fired_at"], "%Y-%m-%d %H:%M:%S")
        except (ValueError, TypeError):
            last = None
        if last is None or (now - last).total_seconds() >= interval:
            execute(
                "UPDATE reminder_log SET fired_at = ? WHERE id = ?",
                (now.strftime("%Y-%m-%d %H:%M:%S"), log_row["id"]),
            )
            self._emit(exp, "on_time", "到点提醒（未确认）", now)

    def _emit(self, exp: dict, kind: str, message: str, now: datetime) -> None:
        log.info("提醒触发：%s（%s）", exp["title"], kind)
        self.fired.emit(
            {
                "experiment_id": exp["id"],
                "title": exp["title"],
                "kind": kind,
                "message": message,
                "planned_start": exp["planned_start"],
            }
        )

    def _mark(self, exp_id: int, kind: str) -> bool:
        """写入提醒日志；返回 True 表示本次是新触发。"""
        with db() as conn:
            cur = conn.execute(
                "INSERT OR IGNORE INTO reminder_log(experiment_id, remind_type, scheduled_for) "
                "VALUES (?, ?, ?)",
                (exp_id, kind, datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
            )
            return cur.rowcount == 1

    def mark_confirmed(self, exp_id: int, kind: str) -> None:
        """用户确认提醒后调用，停止到点提醒的重复响铃。"""
        execute(
            "UPDATE reminder_log SET confirmed = 1 WHERE experiment_id = ? AND remind_type = ?",
            (exp_id, kind),
        )

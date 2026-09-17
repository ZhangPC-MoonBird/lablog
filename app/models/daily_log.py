"""每日记录（daily_logs）与跨日结转。

- get_or_create：启动 / 跨日时确保当天有一条记录（log_date UNIQUE）
- carry_over_unfinished：把某天未完成的实验平移到新日期（时间不变，重算结束时间）
"""
from __future__ import annotations

from ..database import execute, fetch_all, fetch_one, now_str
from ..utils import time_utils


def get_or_create(log_date: str) -> dict:
    """确保某天有每日记录，返回该记录。幂等。"""
    row = fetch_one("SELECT * FROM daily_logs WHERE log_date = ?", (log_date,))
    if row:
        return row
    execute("INSERT INTO daily_logs(log_date, content) VALUES(?, '')", (log_date,))
    return fetch_one("SELECT * FROM daily_logs WHERE log_date = ?", (log_date,))


def get_by_date(log_date: str) -> dict | None:
    return fetch_one("SELECT * FROM daily_logs WHERE log_date = ?", (log_date,))


def save_content(log_date: str, content: str) -> None:
    """保存（覆盖）某天的记录内容，不存在则先创建。"""
    get_or_create(log_date)
    execute(
        "UPDATE daily_logs SET content = ?, updated_at = ? WHERE log_date = ?",
        (content, now_str(), log_date),
    )


def append_content(log_date: str, text: str) -> None:
    """在末尾追加一行说明（跨日结转等）。"""
    cur = get_by_date(log_date)
    existing = (cur["content"] or "").rstrip() if cur else ""
    new = (existing + "\n" + text).strip() if existing else text
    save_content(log_date, new)


def carry_over_unfinished(from_date: str, to_date: str) -> list[str]:
    """把 from_date 未完成（planned/running）的实验平移到 to_date。

    返回结转说明文字列表（用于追加到今日记录）。
    """
    exps = fetch_all(
        "SELECT * FROM experiments "
        "WHERE substr(planned_start, 1, 10) = ? AND status IN ('planned','running')",
        (from_date,),
    )
    notes: list[str] = []
    for e in exps:
        time_part = (e["planned_start"] or "")[11:] or "00:00"
        new_start = f"{to_date} {time_part}"
        new_end = time_utils.end_time_str(new_start, int(e["duration_min"] or 0))
        execute(
            "UPDATE experiments SET planned_start = ?, planned_end = ?, updated_at = ? WHERE id = ?",
            (new_start, new_end, now_str(), e["id"]),
        )
        # 重新武装提醒（时间变了）
        execute("DELETE FROM reminder_log WHERE experiment_id = ?", (e["id"],))
        notes.append(f"{e['title']}：{from_date} → {to_date}")
    return notes

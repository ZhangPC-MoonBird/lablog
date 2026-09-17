"""实验计划数据访问层（experiments 表）。

所有对 experiments 表的读写都收口到这里；UI 与服务层不直接写 SQL。
创建/更新时统一在此计算 planned_end（含跨天）。
"""
from __future__ import annotations

import json
from typing import Any

from ..database import execute, fetch_all, fetch_one, get_setting, now_str, set_setting
from ..utils import time_utils

# 状态 / 优先级枚举与中文映射（UI 共用）
STATUS_LABELS = {
    "planned": "未开始",
    "running": "进行中",
    "done": "已完成",
    "failed": "失败",
    "paused": "已暂停",
    "cancelled": "已取消",
}
STATUS_COLORS = {
    "planned": "subtext",
    "running": "primary",
    "done": "success",
    "failed": "danger",
    "paused": "warning",
    "cancelled": "subtext",
}
PRIORITY_LABELS = {"high": "高", "medium": "中", "low": "低"}
PRIORITY_COLORS = {"high": "danger", "medium": "warning", "low": "subtext"}

# 建议的实验类型（首次使用时的默认清单，之后可由用户在“管理类型”里自定义）
DEFAULT_TYPES = ["合成质粒", "分子克隆", "细胞培养", "蛋白表达", "测序送样", "数据分析", "其他"]

_TYPES_SETTING = "experiment_types"


def get_types() -> list[str]:
    """用户管理的实验类型清单（持久化在 settings，未设置时用默认值）。"""
    types = get_setting(_TYPES_SETTING, None)
    if types is None:
        types = list(DEFAULT_TYPES)
        set_setting(_TYPES_SETTING, types)
    return [t.strip() for t in types if t and t.strip()]


def set_types(types: list[str]) -> None:
    """保存用户自定义的实验类型清单。"""
    set_setting(_TYPES_SETTING, [t.strip() for t in types if t and t.strip()])


def all_types() -> list[str]:
    """下拉用：用户清单 + 历史实验已用过的类型（去重保序，历史数据不丢）。"""
    result = list(get_types())
    for t in distinct_types():
        if t not in result:
            result.append(t)
    return result

# 参与 create / update 的字段（planned_end 单独计算，source 走默认值）
FIELDS = (
    "title", "type", "goal", "steps",
    "planned_start", "duration_min", "planned_end",
    "actual_start", "actual_end", "status", "priority",
    "tags", "notes",
    "remind_enabled", "remind_advance_min", "remind_on_time", "remind_end_min",
)


def _normalize(data: dict) -> dict:
    """把 UI 传入的字段规整为可落库的 dict（含自动计算 planned_end）。"""
    d: dict[str, Any] = {f: data.get(f) for f in FIELDS}
    d["title"] = (d.get("title") or "").strip()
    d["duration_min"] = int(d.get("duration_min") or 0)
    d["status"] = d.get("status") or "planned"
    d["priority"] = d.get("priority") or "medium"
    tags = d.get("tags")
    if isinstance(tags, str):
        try:
            tags = json.loads(tags)
        except (TypeError, ValueError):
            tags = [t.strip() for t in tags.split(",") if t.strip()]
    d["tags"] = json.dumps(tags or [], ensure_ascii=False)
    d["remind_enabled"] = int(d.get("remind_enabled") or 0)
    d["remind_advance_min"] = int(d.get("remind_advance_min") or 0)
    d["remind_on_time"] = int(d.get("remind_on_time") or 0)
    d["remind_end_min"] = int(d.get("remind_end_min") or 0)
    # 自动计算结束时间（正确处理跨天，如 23:00 + 3h -> 次日 02:00）
    d["planned_end"] = (
        time_utils.end_time_str(d.get("planned_start") or "", d["duration_min"])
        if d["planned_start"]
        else ""
    )
    return d


def create(data: dict) -> int:
    """新建实验，返回新 id。"""
    d = _normalize(data)
    cols = ", ".join(FIELDS)
    placeholders = ", ".join("?" * len(FIELDS))
    return execute(
        f"INSERT INTO experiments ({cols}) VALUES ({placeholders})",
        [d[f] for f in FIELDS],
    )


def update(exp_id: int, data: dict) -> None:
    """更新实验；修改计划时间/提醒后清空提醒日志，重新武装提醒。"""
    d = _normalize(data)
    set_clause = ", ".join(f"{f} = ?" for f in FIELDS)
    execute(
        f"UPDATE experiments SET {set_clause}, updated_at = ? WHERE id = ?",
        [d[f] for f in FIELDS] + [now_str(), exp_id],
    )
    execute("DELETE FROM reminder_log WHERE experiment_id = ?", (exp_id,))


def delete(exp_id: int) -> None:
    """删除实验（记录/图片经外键级联删除）。"""
    execute("DELETE FROM experiments WHERE id = ?", (exp_id,))


def get(exp_id: int) -> dict | None:
    return fetch_one("SELECT * FROM experiments WHERE id = ?", (exp_id,))


def list_experiments(
    status: str | None = None,
    type_: str | None = None,
    keyword: str | None = None,
) -> list[dict]:
    """按状态 / 类型 / 关键词过滤，按计划时间升序。"""
    sql = "SELECT * FROM experiments WHERE 1=1"
    params: list[Any] = []
    if status and status != "all":
        sql += " AND status = ?"
        params.append(status)
    if type_ and type_ != "all":
        sql += " AND type = ?"
        params.append(type_)
    if keyword and keyword.strip():
        like = f"%{keyword.strip()}%"
        sql += " AND (title LIKE ? OR goal LIKE ? OR notes LIKE ?)"
        params += [like, like, like]
    sql += " ORDER BY planned_start IS NULL, planned_start ASC, id ASC"
    return fetch_all(sql, params)


def distinct_types() -> list[str]:
    rows = fetch_all(
        "SELECT DISTINCT type FROM experiments WHERE type != '' AND type IS NOT NULL ORDER BY type"
    )
    return [r["type"] for r in rows]


def set_status(exp_id: int, status: str) -> None:
    execute(
        "UPDATE experiments SET status = ?, updated_at = ? WHERE id = ?",
        (status, now_str(), exp_id),
    )


def mark_started(exp_id: int) -> None:
    """开始实验：状态转进行中，补录实际开始时间。"""
    now = now_str()
    execute(
        "UPDATE experiments SET status = 'running', "
        "actual_start = COALESCE(actual_start, ?), updated_at = ? WHERE id = ?",
        (now, now, exp_id),
    )


def mark_finished(exp_id: int) -> None:
    """完成实验：状态转已完成，补录实际结束（与开始）时间。"""
    now = now_str()
    execute(
        "UPDATE experiments SET status = 'done', "
        "actual_end = ?, actual_start = COALESCE(actual_start, ?), updated_at = ? WHERE id = ?",
        (now, now, now, exp_id),
    )


def save_conclusion(exp_id: int, conclusion: str) -> None:
    """保存实验结论（仅更新 conclusion，不影响提醒队列）。"""
    execute(
        "UPDATE experiments SET conclusion = ?, updated_at = ? WHERE id = ?",
        (conclusion, now_str(), exp_id),
    )


def tags_to_str(exp: dict) -> str:
    """tags 字段（JSON 字符串）-> 展示用逗号分隔文本。"""
    try:
        tags = json.loads(exp.get("tags") or "[]")
    except (TypeError, ValueError):
        tags = []
    return ", ".join(tags) if isinstance(tags, list) else str(tags)

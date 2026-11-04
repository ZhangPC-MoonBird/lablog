"""实验计划数据访问层（experiments 表）。

所有对 experiments 表的读写都收口到这里；UI 与服务层不直接写 SQL。
创建/更新时统一在此计算 planned_end（含跨天）。
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from ..database import execute, fetch_all, fetch_one, get_setting, now_str, set_setting
from ..utils import image_utils, time_utils

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
    "parent_id", "follow_offset_min",
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
    parent_id = d.get("parent_id")
    d["parent_id"] = int(parent_id) if parent_id else None
    d["follow_offset_min"] = int(d.get("follow_offset_min") or 0)
    # 自动计算结束时间（正确处理跨天，如 23:00 + 3h -> 次日 02:00）
    d["planned_end"] = (
        time_utils.end_time_str(d.get("planned_start") or "", d["duration_min"])
        if d["planned_start"]
        else ""
    )
    return d


def create(data: dict) -> int:
    """新建实验，返回新 id。source 仅在创建时写入（manual / plan / followup）。"""
    d = _normalize(data)
    cols = ", ".join(FIELDS)
    placeholders = ", ".join("?" * len(FIELDS))
    exp_id = execute(
        f"INSERT INTO experiments ({cols}) VALUES ({placeholders})",
        [d[f] for f in FIELDS],
    )
    source = (data.get("source") or "").strip()
    if source:
        execute("UPDATE experiments SET source = ? WHERE id = ?", (source, exp_id))
    return exp_id


def update(exp_id: int, data: dict, sync_plan: bool = True) -> None:
    """更新实验；修改计划时间/提醒后清空提醒日志，重新武装提醒。

    sync_plan=False 用于“规划页拖动 → 同步实验”的单向更新，避免回写循环。
    """
    d = _normalize(data)
    set_clause = ", ".join(f"{f} = ?" for f in FIELDS)
    execute(
        f"UPDATE experiments SET {set_clause}, updated_at = ? WHERE id = ?",
        [d[f] for f in FIELDS] + [now_str(), exp_id],
    )
    execute("DELETE FROM reminder_log WHERE experiment_id = ?", (exp_id,))
    _recompute_follow_offset(exp_id, d)
    reschedule_followups(exp_id)
    if sync_plan:
        _sync_linked_plan_item(exp_id)


def delete(exp_id: int) -> None:
    """删除实验（记录/图片/跟随实验经外键级联删除，并清理图片文件）。"""
    descendant_ids = _descendant_ids(exp_id)
    all_ids = [exp_id] + descendant_ids
    placeholders = ", ".join("?" * len(all_ids))
    for img in fetch_all(
        f"SELECT path FROM record_images WHERE experiment_id IN ({placeholders})", all_ids
    ):
        if img.get("path"):
            image_utils.delete_image(img["path"])
    for cid in descendant_ids:
        execute("DELETE FROM experiments WHERE id = ?", (cid,))
    execute("DELETE FROM experiments WHERE id = ?", (exp_id,))


def get(exp_id: int) -> dict | None:
    return fetch_one("SELECT * FROM experiments WHERE id = ?", (exp_id,))


def list_experiments(
    status: str | None = None,
    type_: str | None = None,
    keyword: str | None = None,
    follow_scope: str = "all",
) -> list[dict]:
    """按状态 / 类型 / 关键词 / 跟随范围过滤，按计划时间升序。"""
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
    if follow_scope == "main":
        sql += " AND parent_id IS NULL"
    elif follow_scope == "followup":
        sql += " AND parent_id IS NOT NULL"
    sql += " ORDER BY planned_start IS NULL, planned_start ASC, id ASC"
    return fetch_all(sql, params)


def list_for_overview(
    status: str | None = None,
    type_: str | None = None,
    keyword: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> list[dict]:
    """实验总览：按“实际开始 → 计划开始 → 创建时间”归组，附带跟随数量与主实验名。"""
    sql = (
        "SELECT * FROM ("
        "SELECT e.*, "
        "COALESCE(NULLIF(substr(e.actual_start,1,10),''), "
        "NULLIF(substr(e.planned_start,1,10),''), substr(e.created_at,1,10)) AS overview_date, "
        "(SELECT COUNT(*) FROM experiments f WHERE f.parent_id = e.id) AS followup_count, "
        "(SELECT p.title FROM experiments p WHERE p.id = e.parent_id) AS parent_title "
        "FROM experiments e) t WHERE 1=1"
    )
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
    if start_date:
        sql += " AND overview_date >= ?"
        params.append(start_date)
    if end_date:
        sql += " AND overview_date <= ?"
        params.append(end_date)
    sql += " ORDER BY overview_date DESC, planned_start DESC, id DESC"
    return fetch_all(sql, params)


# ---------------------------------------------------------------------------
# 跟随实验：主实验结束后按偏移时间自动开始，可并行多个
# ---------------------------------------------------------------------------
def list_followups(parent_id: int) -> list[dict]:
    return fetch_all(
        "SELECT * FROM experiments WHERE parent_id = ? "
        "ORDER BY follow_offset_min, planned_start, id",
        (parent_id,),
    )


def followup_specs(parent_id: int) -> list[dict]:
    """把跟随实验转成表单可编辑的规格（相对结束时间，不依赖绝对日期）。"""
    return [
        {
            "id": f["id"],
            "title": f["title"],
            "type": f["type"] or "",
            "goal": f["goal"] or "",
            "steps": f["steps"] or "",
            "offset_min": int(f["follow_offset_min"] or 0),
            "duration_min": int(f["duration_min"] or 0),
            "notes": f["notes"] or "",
        }
        for f in list_followups(parent_id)
    ]


def _default_remind() -> tuple[int, int]:
    advance = int(get_setting("remind_default_advance_min", 10) or 0)
    on_time = int(bool(get_setting("remind_default_on_time", True)))
    return advance, on_time


def _followup_start(parent: dict | None, offset_min: int) -> str:
    base = ""
    if parent:
        base = parent.get("planned_end") or parent.get("planned_start") or ""
    if not base:
        return ""
    return time_utils.end_time_str(base, int(offset_min or 0))


def create_followup(parent_id: int, spec: dict) -> int:
    """按主实验结束时间 + 跟随偏移创建一条跟随实验。"""
    parent = get(parent_id)
    offset = int(spec.get("offset_min") or 0)
    duration = int(spec.get("duration_min") or 0)
    start = _followup_start(parent, offset)
    advance, on_time = _default_remind()
    title = (spec.get("title") or "").strip() or "跟随实验"
    return create({
        "title": title,
        "type": spec.get("type") or (parent["type"] if parent else ""),
        "goal": spec.get("goal") or "",
        "steps": spec.get("steps") or "",
        "planned_start": start,
        "duration_min": duration,
        "status": "planned",
        "priority": parent["priority"] if parent else "medium",
        "tags": [],
        "notes": spec.get("notes") or "",
        "remind_enabled": 1 if start else 0,
        "remind_advance_min": advance,
        "remind_on_time": on_time,
        "remind_end_min": 0,
        "parent_id": parent_id,
        "follow_offset_min": offset,
        "source": "followup",
    })


def _set_child_schedule(child: dict, start: str, end: str) -> None:
    """只在时间变化时改写跟随实验计划，避免重复武装提醒。"""
    if start == (child.get("planned_start") or "") and end == (child.get("planned_end") or ""):
        return
    execute(
        "UPDATE experiments SET planned_start = ?, planned_end = ?, updated_at = ? WHERE id = ?",
        (start, end, now_str(), child["id"]),
    )
    execute("DELETE FROM reminder_log WHERE experiment_id = ?", (child["id"],))


def sync_followups(parent_id: int, specs: list[dict]) -> list[dict]:
    """把表单里的跟随实验规格同步到 experiments 子表。

    带 id 的规格更新原跟随实验（保留记录/状态），新规格创建，删除表单里已移除的。
    返回带真实 id 的最新规格，供模板/规划项保存时回写。
    """
    parent = get(parent_id)
    existing = {f["id"]: f for f in list_followups(parent_id)}
    seen: set[int] = set()
    for spec in specs or []:
        sid = spec.get("id")
        title = (spec.get("title") or "").strip() or "跟随实验"
        type_ = (spec.get("type") or "").strip()
        goal = spec.get("goal") or ""
        steps = spec.get("steps") or ""
        offset = int(spec.get("offset_min") or 0)
        duration = int(spec.get("duration_min") or 0)
        notes = spec.get("notes") or ""
        start = _followup_start(parent, offset)
        end = time_utils.end_time_str(start, duration) if start else ""
        if sid and int(sid) in existing:
            child = existing[int(sid)]
            seen.add(int(sid))
            execute(
                "UPDATE experiments SET title = ?, type = ?, goal = ?, steps = ?, notes = ?, "
                "follow_offset_min = ?, duration_min = ?, updated_at = ? WHERE id = ?",
                (title, type_, goal, steps, notes, offset, duration, now_str(), child["id"]),
            )
            _set_child_schedule(child, start, end)
        else:
            create_followup(parent_id, {
                "title": title, "type": type_, "goal": goal, "steps": steps,
                "offset_min": offset, "duration_min": duration, "notes": notes,
            })
    for sid, child in existing.items():
        if sid not in seen:
            delete(child["id"])
    _sync_linked_plan_item(parent_id)
    return followup_specs(parent_id)


def reschedule_followups(parent_id: int) -> None:
    """主实验时间变化后，按“结束时间 + 跟随偏移”整体平移所有跟随实验。"""
    parent = get(parent_id)
    if parent is None:
        return
    for child in list_followups(parent_id):
        start = _followup_start(parent, int(child["follow_offset_min"] or 0))
        end = time_utils.end_time_str(start, int(child["duration_min"] or 0)) if start else ""
        _set_child_schedule(child, start, end)


def followup_count(parent_id: int) -> int:
    row = fetch_one("SELECT COUNT(*) c FROM experiments WHERE parent_id = ?", (parent_id,))
    return row["c"] if row else 0


def _descendant_ids(exp_id: int) -> list[int]:
    result: list[int] = []
    stack = [exp_id]
    while stack:
        cur = stack.pop()
        for row in fetch_all("SELECT id FROM experiments WHERE parent_id = ?", (cur,)):
            result.append(row["id"])
            stack.append(row["id"])
    return result


def _recompute_follow_offset(exp_id: int, data: dict) -> None:
    """直接编辑跟随实验的开始时间时，反推它相对主实验结束的偏移。"""
    parent_id = data.get("parent_id")
    start = data.get("planned_start")
    if not parent_id or not start:
        return
    parent = get(int(parent_id))
    if parent is None or not parent.get("planned_end"):
        return
    try:
        base = datetime.strptime(parent["planned_end"], "%Y-%m-%d %H:%M")
        child = datetime.strptime(start, "%Y-%m-%d %H:%M")
    except (ValueError, TypeError):
        return
    offset = int((child - base).total_seconds() // 60)
    execute("UPDATE experiments SET follow_offset_min = ? WHERE id = ?", (offset, exp_id))


def _sync_linked_plan_item(exp_id: int) -> None:
    """实验与规划项双向统一：改实验后把标题/时间/完整字段写回已关联规划项。"""
    exp = get(exp_id)
    if exp is None:
        return
    item = fetch_one(
        "SELECT * FROM plan_items WHERE linked_experiment_id = ? ORDER BY id LIMIT 1",
        (exp_id,),
    )
    if item is None:
        return
    start = exp.get("planned_start") or ""
    planned_date = start[:10] or item["planned_date"]
    planned_start = start[11:16] or item["planned_start"]
    planned_end = (
        time_utils.minutes_to_time(time_utils.time_to_minutes(planned_start) + int(exp["duration_min"] or 0))
        if planned_start else ""
    )
    execute(
        "UPDATE plan_items SET title = ?, type = ?, planned_date = ?, planned_start = ?, "
        "duration_min = ?, planned_end = ?, priority = ?, notes = ?, goal = ?, steps = ?, "
        "tags = ?, remind_enabled = ?, remind_advance_min = ?, remind_on_time = ?, "
        "remind_end_min = ?, followups = ?, is_experiment = 1, updated_at = ? WHERE id = ?",
        (
            exp["title"], exp["type"] or "", planned_date, planned_start,
            int(exp["duration_min"] or 0), planned_end, exp["priority"],
            exp["notes"] or "", exp["goal"] or "", exp["steps"] or "",
            exp["tags"] or "[]", int(exp["remind_enabled"] or 0),
            int(exp["remind_advance_min"] or 0), int(exp["remind_on_time"] or 0),
            int(exp["remind_end_min"] or 0),
            json.dumps(followup_specs(exp_id), ensure_ascii=False), now_str(), item["id"],
        ),
    )


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

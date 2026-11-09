"""周整理（weekly_reviews）与实验规划（weekly_plans / plan_items）数据访问层。

- 周汇总统计实时计算，不落库
- 规划项拖拽后调用 reorder_date / set_item_date_order 持久化 sort_order
- 一键转实验在 experiments 表创建正式实验并回写 linked_experiment_id
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from typing import Any

from ..database import execute, fetch_all, fetch_one, get_setting, now_str
from ..utils import time_utils
from . import experiment


def _json_list(value) -> list:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            value = []
    return value if isinstance(value, list) else []


def _json_dump(value) -> str:
    return json.dumps(_json_list(value), ensure_ascii=False)


def week_bounds(week_start: str) -> tuple[str, str]:
    """由周一日期返回 (周一, 周日) 字符串。"""
    monday = datetime.strptime(week_start, "%Y-%m-%d").date()
    monday = time_utils.monday_of(monday)
    sunday = monday + timedelta(days=6)
    return monday.strftime("%Y-%m-%d"), sunday.strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# 周整理
# ---------------------------------------------------------------------------
def get_or_create_review(week_start: str) -> dict:
    row = fetch_one("SELECT * FROM weekly_reviews WHERE week_start = ?", (week_start,))
    if row:
        return row
    execute("INSERT INTO weekly_reviews(week_start) VALUES(?)", (week_start,))
    return fetch_one("SELECT * FROM weekly_reviews WHERE week_start = ?", (week_start,))


def get_review(week_start: str) -> dict | None:
    return fetch_one("SELECT * FROM weekly_reviews WHERE week_start = ?", (week_start,))


def save_review_field(week_start: str, field: str, content: str) -> None:
    """保存三栏之一（summary / problems / next_plan）。"""
    assert field in ("summary", "problems", "next_plan")
    get_or_create_review(week_start)
    execute(
        f"UPDATE weekly_reviews SET {field} = ?, updated_at = ? WHERE week_start = ?",
        (content, now_str(), week_start),
    )


def week_stats(monday: str, sunday: str) -> dict[str, int]:
    """本周统计（实时计算）：完成 / 进行中 / 记录 / 图片 / 失败 / 超时。"""
    def _count(sql: str, params: tuple = ()) -> int:
        return fetch_one(sql, params)["c"]

    done = _count(
        "SELECT COUNT(*) c FROM experiments WHERE status='done' "
        "AND substr(planned_start,1,10) BETWEEN ? AND ?", (monday, sunday))
    running = _count("SELECT COUNT(*) c FROM experiments WHERE status='running'")
    records = _count(
        "SELECT COUNT(*) c FROM experiment_records WHERE substr(record_time,1,10) BETWEEN ? AND ?",
        (monday, sunday))
    # 图片数：record_images 表里的 + 记录正文 Markdown 引用的（去重，避免重复计数）
    image_paths: set[str] = set()
    for row in fetch_all(
        "SELECT ri.path AS p FROM record_images ri "
        "JOIN experiment_records er ON ri.record_id = er.id "
        "WHERE substr(er.record_time,1,10) BETWEEN ? AND ?", (monday, sunday)):
        image_paths.add(row["p"] or "")
    for row in fetch_all(
        "SELECT content FROM experiment_records "
        "WHERE substr(record_time,1,10) BETWEEN ? AND ?", (monday, sunday)):
        image_paths.update(
            m for m in re.findall(r"!\[[^\]]*\]\(([^)]+)\)", row["content"] or "")
            if m.startswith("images/"))
    images = len(image_paths)
    failed = _count(
        "SELECT COUNT(*) c FROM experiments WHERE status='failed' "
        "AND substr(planned_start,1,10) BETWEEN ? AND ?", (monday, sunday))
    overdue = _count(
        "SELECT COUNT(*) c FROM experiments WHERE status IN ('planned','running') "
        "AND planned_end IS NOT NULL AND planned_end != '' "
        "AND planned_end < datetime('now','localtime')")
    return {
        "done": done, "running": running, "records": records,
        "images": images, "failed": failed, "overdue": overdue,
    }


def week_experiments(monday: str, sunday: str) -> list[dict]:
    """本周“做过”的实验：计划/实际开始/实际结束/记录时间任一项落在本周。

    用于周整理展示与周报导出。
    """
    return fetch_all(
        "SELECT DISTINCT e.* FROM experiments e "
        "LEFT JOIN experiment_records r ON r.experiment_id = e.id "
        "WHERE substr(e.planned_start,1,10) BETWEEN ? AND ? "
        "OR substr(e.actual_start,1,10) BETWEEN ? AND ? "
        "OR substr(e.actual_end,1,10) BETWEEN ? AND ? "
        "OR substr(r.record_time,1,10) BETWEEN ? AND ? "
        "ORDER BY e.planned_start",
        (monday, sunday, monday, sunday, monday, sunday, monday, sunday))


# ---------------------------------------------------------------------------
# 实验规划
# ---------------------------------------------------------------------------
def get_or_create_plan(week_start: str) -> dict:
    row = fetch_one("SELECT * FROM weekly_plans WHERE week_start = ?", (week_start,))
    if row:
        return row
    execute("INSERT INTO weekly_plans(week_start) VALUES(?)", (week_start,))
    return fetch_one("SELECT * FROM weekly_plans WHERE week_start = ?", (week_start,))


def list_items_range(start_date: str, end_date: str) -> list[dict]:
    return fetch_all(
        "SELECT * FROM plan_items WHERE planned_date BETWEEN ? AND ? "
        "ORDER BY planned_date, sort_order, id", (start_date, end_date))


def get_item(item_id: int) -> dict | None:
    return fetch_one("SELECT * FROM plan_items WHERE id = ?", (item_id,))


def create_item(data: dict) -> int:
    """创建规划项。data 需含 week_start / title / planned_date；自动计算 planned_end 与 sort_order。"""
    plan = get_or_create_plan(data["week_start"])
    planned_start = data.get("planned_start") or ""
    duration = int(data.get("duration_min") or 0)
    planned_end = (
        time_utils.minutes_to_time(time_utils.time_to_minutes(planned_start) + duration)
        if planned_start else ""
    )
    max_order = fetch_one(
        "SELECT COALESCE(MAX(sort_order), -1) m FROM plan_items WHERE planned_date = ?",
        (data["planned_date"],))["m"]
    on_time = data.get("remind_on_time")
    on_time = 1 if on_time is None else int(bool(on_time))
    return execute(
        "INSERT INTO plan_items(weekly_plan_id, title, type, planned_date, planned_start, "
        "duration_min, planned_end, priority, notes, sort_order, is_experiment, goal, steps, "
        "tags, remind_enabled, remind_advance_min, remind_on_time, remind_end_min, followups) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (plan["id"], data["title"], data.get("type", ""), data["planned_date"],
         planned_start, duration, planned_end, data.get("priority", "medium"),
         data.get("notes", ""), max_order + 1,
         int(bool(data.get("is_experiment"))), data.get("goal", ""), data.get("steps", ""),
         _json_dump(data.get("tags")), int(data.get("remind_enabled") or 0),
         int(data.get("remind_advance_min") or 0), on_time,
         int(data.get("remind_end_min") or 0), _json_dump(data.get("followups"))),
    )


def update_item(item_id: int, data: dict, sync_experiment: bool = True) -> None:
    d = dict(data)
    d.pop("week_start", None)  # 仅在 create_item 使用，plan_items 无此列
    if "planned_start" in d or "duration_min" in d:
        item = get_item(item_id)
        start = d.get("planned_start", item["planned_start"])
        dur = int(d.get("duration_min", item["duration_min"] or 0))
        d["planned_end"] = (
            time_utils.minutes_to_time(time_utils.time_to_minutes(start) + dur) if start else ""
        )
    if "tags" in d:
        d["tags"] = _json_dump(d["tags"])
    if "followups" in d:
        d["followups"] = _json_dump(d["followups"])
    if "is_experiment" in d:
        d["is_experiment"] = int(bool(d["is_experiment"]))
    if not d:
        return
    sets = ", ".join(f"{k} = ?" for k in d)
    execute(
        f"UPDATE plan_items SET {sets}, updated_at = ? WHERE id = ?",
        list(d.values()) + [now_str(), item_id],
    )
    if sync_experiment:
        _sync_linked_experiment(item_id, sync_followups="followups" in data)


def delete_item(item_id: int) -> None:
    execute("DELETE FROM plan_items WHERE id = ?", (item_id,))


def set_item_date_order(item_id: int, planned_date: str, sort_order: int) -> None:
    execute(
        "UPDATE plan_items SET planned_date = ?, sort_order = ?, updated_at = ? WHERE id = ?",
        (planned_date, sort_order, now_str(), item_id),
    )
    _sync_linked_experiment(item_id)


def reorder_date(planned_date: str, ordered_ids: list[int]) -> None:
    """按给定顺序重排某一天所有规划项的 sort_order。"""
    for i, item_id in enumerate(ordered_ids):
        execute(
            "UPDATE plan_items SET sort_order = ?, updated_at = ? "
            "WHERE id = ? AND planned_date = ?",
            (i, now_str(), item_id, planned_date),
        )


def _sync_linked_experiment(item_id: int, sync_followups: bool = False) -> None:
    """规划项改动后同步已关联实验；改时间时跟随实验也一起平移。"""
    item = get_item(item_id)
    if item is None or not item.get("linked_experiment_id"):
        return
    exp = experiment.get(item["linked_experiment_id"])
    if exp is None:
        return
    is_experiment = bool(item.get("is_experiment"))
    start = f"{item['planned_date']} {item['planned_start'] or '09:00'}"
    data = {
        "title": item["title"], "type": item["type"] or "",
        "goal": (item["goal"] or "") if is_experiment else exp["goal"] or "",
        "steps": (item["steps"] or "") if is_experiment else exp["steps"] or "",
        "planned_start": start, "duration_min": int(item["duration_min"] or 0),
        "actual_start": exp["actual_start"], "actual_end": exp["actual_end"],
        "status": exp["status"], "priority": item["priority"],
        "tags": _json_list(item["tags"]) if is_experiment else _json_list(exp["tags"]),
        "notes": item["notes"] or "",
        "remind_enabled": int(item["remind_enabled"] or 0) if is_experiment else int(exp["remind_enabled"] or 0),
        "remind_advance_min": int(item["remind_advance_min"] or 0) if is_experiment else int(exp["remind_advance_min"] or 0),
        "remind_on_time": int(item["remind_on_time"] or 0) if is_experiment else int(exp["remind_on_time"] or 0),
        "remind_end_min": int(item["remind_end_min"] or 0) if is_experiment else int(exp["remind_end_min"] or 0),
        "parent_id": exp["parent_id"], "follow_offset_min": exp["follow_offset_min"] or 0,
    }
    experiment.update(int(exp["id"]), data, sync_plan=False)
    if sync_followups and is_experiment:
        experiment.sync_followups(int(exp["id"]), _json_list(item["followups"]))


def copy_week(from_week_start: str, to_week_start: str) -> list[int]:
    """把 from_week 一整周的规划项复制到 to_week（日期按周偏移）。"""
    from_m, from_s = week_bounds(from_week_start)
    offset = (
        datetime.strptime(to_week_start, "%Y-%m-%d").date()
        - datetime.strptime(from_m, "%Y-%m-%d").date()
    ).days
    created: list[int] = []
    for it in list_items_range(from_m, from_s):
        new_date = (datetime.strptime(it["planned_date"], "%Y-%m-%d") + timedelta(days=offset)).strftime("%Y-%m-%d")
        # 复制时去掉跟随实验的数据库 id，让新规划项转实验时创建全新的跟随实验
        followups = [
            {k: v for k, v in spec.items() if k != "id"}
            for spec in _json_list(it.get("followups"))
        ]
        created.append(create_item({
            "week_start": to_week_start, "title": it["title"], "type": it["type"],
            "planned_date": new_date, "planned_start": it["planned_start"],
            "duration_min": it["duration_min"], "priority": it["priority"],
            "notes": it["notes"], "is_experiment": it.get("is_experiment") or 0,
            "goal": it.get("goal") or "", "steps": it.get("steps") or "",
            "tags": _json_list(it.get("tags")), "followups": followups,
            "remind_enabled": it.get("remind_enabled") or 0,
            "remind_advance_min": it.get("remind_advance_min") or 0,
            "remind_on_time": it.get("remind_on_time"),
            "remind_end_min": it.get("remind_end_min") or 0,
        }))
    return created


# 模板：通用实验周安排（标题, 星期索引 0=周一, 开始, 耗时分钟, 优先级）
DEFAULT_TEMPLATE = [
    ("文献阅读与实验准备", 0, "09:00", 120, "medium"),
    ("细胞传代", 1, "10:00", 90, "high"),
    ("质粒构建", 2, "14:00", 180, "high"),
    ("数据分析", 4, "09:00", 120, "medium"),
    ("组会汇报", 4, "15:00", 60, "medium"),
]


def create_from_template(to_week_start: str) -> list[int]:
    """按默认模板创建一周规划。"""
    monday = datetime.strptime(to_week_start, "%Y-%m-%d").date()
    created: list[int] = []
    for title, dow, start, dur, prio in DEFAULT_TEMPLATE:
        d = (monday + timedelta(days=dow)).strftime("%Y-%m-%d")
        created.append(create_item({
            "week_start": to_week_start, "title": title, "type": "",
            "planned_date": d, "planned_start": start, "duration_min": dur,
            "priority": prio, "notes": "",
        }))
    return created


def find_plan_item_for_experiment(exp_id: int) -> dict | None:
    """某个实验已关联的规划项（用于“转规划”按钮显示状态/去重）。"""
    return fetch_one(
        "SELECT * FROM plan_items WHERE linked_experiment_id = ? ORDER BY id LIMIT 1",
        (exp_id,),
    )


def _experiment_plan_date(exp: dict) -> str:
    """转规划默认使用实验开始日期（计划开始优先，其次实际开始，最后今天）。"""
    start = (exp.get("planned_start") or "")[:10]
    if start:
        return start
    actual = (exp.get("actual_start") or "")[:10]
    return actual or datetime.now().strftime("%Y-%m-%d")


def _experiment_plan_data(exp: dict, target_date: str) -> dict:
    """实验 -> 规划项字段（完整保留目标/步骤/提醒/跟随，转过去不用重写）。"""
    source_start = exp["planned_start"] or exp.get("actual_start") or ""
    time_part = source_start[11:16] or "09:00"
    week_start = time_utils.monday_of(
        datetime.strptime(target_date, "%Y-%m-%d").date()).strftime("%Y-%m-%d")
    return {
        "week_start": week_start,
        "title": exp["title"],
        "type": exp["type"] or "",
        "planned_date": target_date,
        "planned_start": time_part,
        "duration_min": int(exp["duration_min"] or 0),
        "priority": exp["priority"],
        "notes": exp["notes"] or "",
        "is_experiment": 1,
        "goal": exp["goal"] or "",
        "steps": exp["steps"] or "",
        "tags": _json_list(exp.get("tags")),
        "remind_enabled": int(exp["remind_enabled"] or 0),
        "remind_advance_min": int(exp["remind_advance_min"] or 0),
        "remind_on_time": int(exp["remind_on_time"] or 0),
        "remind_end_min": int(exp["remind_end_min"] or 0),
        "followups": experiment.followup_specs(int(exp["id"])),
    }


def convert_experiment_to_plan(exp_id: int, target_date: str | None = None) -> int | None:
    """把实验转成规划项；默认按实验开始日期，已转过则更新原规划项，不重复创建。"""
    exp = experiment.get(exp_id)
    if exp is None:
        return None
    if not target_date:
        target_date = _experiment_plan_date(exp)
    data = _experiment_plan_data(exp, target_date)
    existing = find_plan_item_for_experiment(exp_id)
    if existing is not None:
        update_item(int(existing["id"]), data, sync_experiment=False)
        execute(
            "UPDATE plan_items SET linked_experiment_id = ?, status = 'converted', "
            "is_experiment = 1, updated_at = ? WHERE id = ?",
            (exp_id, now_str(), existing["id"]),
        )
        return int(existing["id"])
    item_id = create_item(data)
    execute(
        "UPDATE plan_items SET linked_experiment_id = ?, status = 'converted', updated_at = ? "
        "WHERE id = ?",
        (exp_id, now_str(), item_id),
    )
    return item_id


def convert_to_experiment(item_id: int) -> int | None:
    """一键转正式实验：完整带入目标/步骤/提醒/跟随实验，回写 linked_experiment_id。"""
    item = get_item(item_id)
    if item is None or item["linked_experiment_id"]:
        return item["linked_experiment_id"] if item else None
    planned_start = f"{item['planned_date']} {item['planned_start'] or '09:00'}"
    duration = int(item["duration_min"] or 0)
    is_experiment = bool(item.get("is_experiment"))
    if is_experiment:
        remind_enabled = int(item["remind_enabled"] or 0)
        advance = int(item["remind_advance_min"] or 0)
        on_time = int(item["remind_on_time"] or 0)
        end_min = int(item["remind_end_min"] or 0)
    else:
        remind_enabled = 1
        advance = int(get_setting("remind_default_advance_min", 10) or 0)
        on_time = int(bool(get_setting("remind_default_on_time", True)))
        end_min = 0
    exp_id = experiment.create({
        "title": item["title"], "type": item["type"] or "",
        "goal": (item["goal"] or "") if is_experiment else "",
        "steps": (item["steps"] or "") if is_experiment else "",
        "planned_start": planned_start, "duration_min": duration,
        "priority": item["priority"],
        "tags": _json_list(item.get("tags")) if is_experiment else [],
        "notes": item["notes"] or "", "status": "planned",
        "remind_enabled": remind_enabled, "remind_advance_min": advance,
        "remind_on_time": on_time, "remind_end_min": end_min,
        "source": "plan",
    })
    specs = experiment.sync_followups(
        exp_id, _json_list(item.get("followups")) if is_experiment else [])
    execute(
        "UPDATE plan_items SET linked_experiment_id = ?, status = 'converted', "
        "followups = ?, updated_at = ? WHERE id = ?",
        (exp_id, _json_dump(specs), now_str(), item_id),
    )
    return exp_id


def week_totals(items: list[dict]) -> dict[str, Any]:
    """规划统计：周总时长 + 每日数量/时长 + 冲突日期。"""
    by_date: dict[str, list[dict]] = {}
    for it in items:
        by_date.setdefault(it["planned_date"], []).append(it)
    total_min = sum(int(it["duration_min"] or 0) for it in items)
    daily = {}
    conflicts: set[str] = set()
    for date, its in by_date.items():
        daily[date] = {
            "count": len(its),
            "minutes": sum(int(it["duration_min"] or 0) for it in its),
        }
        # 时间冲突检测：按开始排序，相邻重叠即冲突
        sorted_its = sorted(its, key=lambda x: time_utils.time_to_minutes(x["planned_start"] or ""))
        for a, b in zip(sorted_its, sorted_its[1:]):
            a_start = time_utils.time_to_minutes(a["planned_start"] or "")
            b_start = time_utils.time_to_minutes(b["planned_start"] or "")
            a_end = a_start + int(a["duration_min"] or 0)
            if a["duration_min"] and b["duration_min"] and a_end > b_start:
                conflicts.add(date)
                break
    return {"total_min": total_min, "daily": daily, "conflicts": conflicts}

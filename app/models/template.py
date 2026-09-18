"""实验模板数据访问层（templates 表）。

同类型实验保存为模板后，新建实验时一键载入，不用重写目标/步骤/提醒设置。
"""
from __future__ import annotations

from ..database import execute, fetch_all, fetch_one

FIELDS = (
    "name", "type", "goal", "steps", "duration_min", "priority",
    "remind_advance_min", "remind_on_time", "remind_end_min", "notes",
)


def list_templates() -> list[dict]:
    return fetch_all("SELECT * FROM templates ORDER BY name, id")


def get(template_id: int) -> dict | None:
    return fetch_one("SELECT * FROM templates WHERE id = ?", (template_id,))


def create(data: dict) -> int:
    d = {f: data.get(f) for f in FIELDS}
    d["name"] = (d.get("name") or "").strip()
    d["priority"] = d.get("priority") or "medium"
    d["duration_min"] = int(d.get("duration_min") or 0)
    d["remind_advance_min"] = int(d.get("remind_advance_min") or 0)
    d["remind_on_time"] = int(d.get("remind_on_time") or 0)
    d["remind_end_min"] = int(d.get("remind_end_min") or 0)
    cols = ", ".join(FIELDS)
    return execute(
        f"INSERT INTO templates ({cols}) VALUES ({', '.join('?' * len(FIELDS))})",
        [d[f] for f in FIELDS],
    )


def update(template_id: int, data: dict) -> None:
    d = {f: data.get(f) for f in FIELDS}
    d["name"] = (d.get("name") or "").strip()
    d["priority"] = d.get("priority") or "medium"
    d["duration_min"] = int(d.get("duration_min") or 0)
    d["remind_advance_min"] = int(d.get("remind_advance_min") or 0)
    d["remind_on_time"] = int(d.get("remind_on_time") or 0)
    d["remind_end_min"] = int(d.get("remind_end_min") or 0)
    set_clause = ", ".join(f"{f} = ?" for f in FIELDS)
    execute(f"UPDATE templates SET {set_clause} WHERE id = ?",
            [d[f] for f in FIELDS] + [template_id])


def delete(template_id: int) -> None:
    execute("DELETE FROM templates WHERE id = ?", (template_id,))

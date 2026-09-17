"""SQLite 数据层：建库、迁移、设置与通用查询助手。

连接策略：每次操作短连接 + WAL 模式，桌面单用户场景下最简单可靠。
时间约定：所有时间以本地时间字符串存储（YYYY-MM-DD HH:MM 或 HH:MM:SS）。
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Sequence

from . import config

SCHEMA_VERSION = 1

# ---------------------------------------------------------------------------
# 表结构（11 张表，一次建全，避免后续里程碑做迁移）
# ---------------------------------------------------------------------------
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS app_meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

-- 设置：key-value，value 为 JSON 文本
CREATE TABLE IF NOT EXISTS settings (
    key        TEXT PRIMARY KEY,
    value      TEXT,
    updated_at TEXT DEFAULT (datetime('now','localtime'))
);

-- 实验计划
CREATE TABLE IF NOT EXISTS experiments (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    title              TEXT NOT NULL,
    type               TEXT DEFAULT '',
    goal               TEXT DEFAULT '',
    steps              TEXT DEFAULT '',
    planned_start      TEXT,                    -- 'YYYY-MM-DD HH:MM'
    duration_min       INTEGER NOT NULL DEFAULT 0,
    planned_end        TEXT,                    -- 由 planned_start + duration_min 计算并冗余存储
    actual_start       TEXT,
    actual_end         TEXT,
    status             TEXT NOT NULL DEFAULT 'planned',
    priority           TEXT NOT NULL DEFAULT 'medium',
    tags               TEXT NOT NULL DEFAULT '[]',  -- JSON 数组
    notes              TEXT DEFAULT '',
    conclusion         TEXT DEFAULT '',             -- 实验结论
    remind_enabled     INTEGER NOT NULL DEFAULT 0,
    remind_advance_min INTEGER NOT NULL DEFAULT 0,  -- 0 = 不提前提醒
    remind_on_time     INTEGER NOT NULL DEFAULT 1,  -- 到点提醒
    remind_end_min     INTEGER NOT NULL DEFAULT 0,  -- 结束前 N 分钟提醒（0 = 不提醒）
    source             TEXT NOT NULL DEFAULT 'manual',  -- manual / plan（来自规划页）
    created_at         TEXT DEFAULT (datetime('now','localtime')),
    updated_at         TEXT DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_exp_status ON experiments(status);
CREATE INDEX IF NOT EXISTS idx_exp_start ON experiments(planned_start);

-- 提醒触发日志：UNIQUE(experiment_id, remind_type) 保证同一次计划只提醒一次
CREATE TABLE IF NOT EXISTS reminder_log (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_id INTEGER NOT NULL REFERENCES experiments(id) ON DELETE CASCADE,
    remind_type   TEXT NOT NULL,                -- advance / on_time / end
    scheduled_for TEXT NOT NULL,
    fired_at      TEXT DEFAULT (datetime('now','localtime')),
    confirmed     INTEGER NOT NULL DEFAULT 0,   -- 到点提醒是否已被用户确认（未确认则重复响）
    UNIQUE (experiment_id, remind_type)
);

-- 实验记录（时间线）
CREATE TABLE IF NOT EXISTS experiment_records (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_id INTEGER NOT NULL REFERENCES experiments(id) ON DELETE CASCADE,
    record_time   TEXT NOT NULL,                -- 'YYYY-MM-DD HH:MM:SS'，默认当前时间，可手改
    content       TEXT DEFAULT '',              -- Markdown，可内嵌图片链接
    created_at    TEXT DEFAULT (datetime('now','localtime')),
    updated_at    TEXT DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_records_exp ON experiment_records(experiment_id, record_time);

-- 记录图片：文件存 data/images/，这里存相对路径，用于统计与清理
CREATE TABLE IF NOT EXISTS record_images (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    record_id     INTEGER REFERENCES experiment_records(id) ON DELETE CASCADE,
    experiment_id INTEGER REFERENCES experiments(id) ON DELETE CASCADE,
    path          TEXT NOT NULL,
    created_at    TEXT DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_images_exp ON record_images(experiment_id);

-- 实验附件（data/files/）
CREATE TABLE IF NOT EXISTS attachments (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_id INTEGER REFERENCES experiments(id) ON DELETE CASCADE,
    name          TEXT,
    path          TEXT NOT NULL,
    created_at    TEXT DEFAULT (datetime('now','localtime'))
);

-- 每日记录：每天一条，应用启动自动创建，跨零点自动切换
CREATE TABLE IF NOT EXISTS daily_logs (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    log_date   TEXT NOT NULL UNIQUE,            -- 'YYYY-MM-DD'
    content    TEXT DEFAULT '',
    created_at TEXT DEFAULT (datetime('now','localtime')),
    updated_at TEXT DEFAULT (datetime('now','localtime'))
);

-- 周整理：每周一条（week_start = 周一）
CREATE TABLE IF NOT EXISTS weekly_reviews (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    week_start TEXT NOT NULL UNIQUE,
    summary    TEXT DEFAULT '',                 -- 本周总结
    problems   TEXT DEFAULT '',                 -- 本周问题
    next_plan  TEXT DEFAULT '',                 -- 下周计划
    created_at TEXT DEFAULT (datetime('now','localtime')),
    updated_at TEXT DEFAULT (datetime('now','localtime'))
);

-- 实验规划：每周一份计划
CREATE TABLE IF NOT EXISTS weekly_plans (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    week_start TEXT NOT NULL UNIQUE,
    created_at TEXT DEFAULT (datetime('now','localtime')),
    updated_at TEXT DEFAULT (datetime('now','localtime'))
);

-- 规划项（按需求规定的字段）
CREATE TABLE IF NOT EXISTS plan_items (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    weekly_plan_id       INTEGER NOT NULL REFERENCES weekly_plans(id) ON DELETE CASCADE,
    title                TEXT NOT NULL,
    type                 TEXT DEFAULT '',
    planned_date         TEXT NOT NULL,         -- 'YYYY-MM-DD'
    planned_start        TEXT DEFAULT '',       -- 'HH:MM'
    duration_min         INTEGER NOT NULL DEFAULT 0,
    planned_end          TEXT DEFAULT '',       -- 'HH:MM'，自动计算
    priority             TEXT NOT NULL DEFAULT 'medium',
    status               TEXT NOT NULL DEFAULT 'planned',
    sort_order           INTEGER NOT NULL DEFAULT 0,  -- 同一天内的拖拽排序
    linked_experiment_id INTEGER REFERENCES experiments(id) ON DELETE SET NULL,
    notes                TEXT DEFAULT '',
    created_at           TEXT DEFAULT (datetime('now','localtime')),
    updated_at           TEXT DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_plan_items_date ON plan_items(planned_date);
CREATE INDEX IF NOT EXISTS idx_plan_items_week ON plan_items(weekly_plan_id);
"""

# 默认设置（写入 settings 表，value 为 JSON 文本）
DEFAULT_SETTINGS: dict[str, Any] = {
    "theme": "light",
    "weather_enabled": False,
    "weather_provider": "qweather",
    "weather_api_key": "",
    "weather_city": "北京",
    "weather_update_min": 30,
    "carry_over_enabled": False,
    "remind_default_advance_min": 10,
    "remind_default_on_time": True,
    "remind_repeat_interval_sec": 5,
    "auto_backup_enabled": False,
    "auto_backup_hour": "21:00",
    "last_backup_at": "",
    "last_weather_at": "",
}


@contextmanager
def db():
    """数据库连接上下文：自动提交 / 回滚 / 关闭。"""
    conn = sqlite3.connect(str(config.DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.execute("PRAGMA journal_mode = WAL").fetchone()
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _migrate(conn) -> None:
    """对旧库做列级迁移（幂等，可重复执行）。"""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(experiments)").fetchall()}
    if "conclusion" not in cols:
        conn.execute("ALTER TABLE experiments ADD COLUMN conclusion TEXT DEFAULT ''")
    if "remind_end_min" not in cols:
        conn.execute("ALTER TABLE experiments ADD COLUMN remind_end_min INTEGER NOT NULL DEFAULT 0")
    rcols = {r["name"] for r in conn.execute("PRAGMA table_info(reminder_log)").fetchall()}
    if "confirmed" not in rcols:
        conn.execute("ALTER TABLE reminder_log ADD COLUMN confirmed INTEGER NOT NULL DEFAULT 0")


def init_db() -> None:
    """初始化数据库：建目录、建表、写默认设置。幂等，可重复调用。"""
    config.ensure_dirs()
    with db() as conn:
        conn.executescript(SCHEMA_SQL)
        # 迁移：为旧库补充新增列（幂等）
        _migrate(conn)
        conn.execute(
            "INSERT OR IGNORE INTO app_meta(key, value) VALUES('schema_version', ?)",
            (str(SCHEMA_VERSION),),
        )
        for key, value in DEFAULT_SETTINGS.items():
            conn.execute(
                "INSERT OR IGNORE INTO settings(key, value) VALUES(?, ?)",
                (key, json.dumps(value, ensure_ascii=False)),
            )


# ---------------------------------------------------------------------------
# 设置读写
# ---------------------------------------------------------------------------
def get_setting(key: str, default: Any = None) -> Any:
    with db() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    if row is None:
        return default
    try:
        return json.loads(row["value"])
    except (TypeError, ValueError):
        return row["value"]


def set_setting(key: str, value: Any) -> None:
    with db() as conn:
        conn.execute(
            "INSERT INTO settings(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, "
            "updated_at = datetime('now','localtime')",
            (key, json.dumps(value, ensure_ascii=False)),
        )


# ---------------------------------------------------------------------------
# 通用查询助手
# ---------------------------------------------------------------------------
def fetch_all(sql: str, params: Sequence = ()) -> list[dict]:
    with db() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def fetch_one(sql: str, params: Sequence = ()) -> dict | None:
    with db() as conn:
        row = conn.execute(sql, params).fetchone()
    return dict(row) if row else None


def execute(sql: str, params: Sequence = ()) -> int:
    """执行写操作，返回 lastrowid。"""
    with db() as conn:
        cur = conn.execute(sql, params)
        return cur.lastrowid


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

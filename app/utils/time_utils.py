"""时间工具：中文日期、星期、结束时间计算、周起止。"""
from __future__ import annotations

from datetime import date, datetime, timedelta

WEEKDAY_CN = "一二三四五六日"


def cn_weekday(d: date | datetime) -> str:
    return f"星期{WEEKDAY_CN[d.weekday()]}"


def format_date_cn(d: datetime) -> str:
    """YYYY年MM月DD日 星期X"""
    return f"{d.strftime('%Y年%m月%d日')} {cn_weekday(d)}"


def monday_of(d: date) -> date:
    """所在周的周一。"""
    return d - timedelta(days=d.weekday())


def week_range(d: date) -> tuple[date, date]:
    """所在周的 (周一, 周日)。"""
    m = monday_of(d)
    return m, m + timedelta(days=6)


def end_time_str(start: str, duration_min: int) -> str:
    """由开始时间 'YYYY-MM-DD HH:MM' 和耗时分钟计算结束时间字符串。"""
    if not start or duration_min < 0:
        return ""
    dt = datetime.strptime(start, "%Y-%m-%d %H:%M") + timedelta(minutes=duration_min)
    return dt.strftime("%Y-%m-%d %H:%M")


def time_to_minutes(t: str) -> int:
    """'HH:MM' -> 分钟数。"""
    try:
        h, m = t.split(":")
        return int(h) * 60 + int(m)
    except (ValueError, AttributeError):
        return 0


def minutes_to_time(total: int) -> str:
    """分钟数 -> 'HH:MM'（跨天取模，超过 24h 视为跨日）。"""
    total %= 24 * 60
    return f"{total // 60:02d}:{total % 60:02d}"


def format_duration(minutes: int) -> str:
    """分钟数 -> 人类可读时长，如 '3小时' / '1小时30分' / '45分'。"""
    minutes = int(minutes or 0)
    if minutes < 0:
        return ""
    h, m = divmod(minutes, 60)
    if h and m:
        return f"{h}小时{m}分"
    if h:
        return f"{h}小时"
    return f"{m}分"

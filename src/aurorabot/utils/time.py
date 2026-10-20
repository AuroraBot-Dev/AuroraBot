"""时间处理工具集。

统一使用 UTC ISO 8601 字符串作为数据库时间戳格式。
"""

from datetime import UTC, datetime


def utc_now() -> str:
    """返回当前 UTC 时间的 ISO 格式字符串，用于所有数据库时间戳统一。"""
    return datetime.now(UTC).isoformat()


def utc_today() -> str:
    """返回当前 UTC 日期（ISO ``YYYY-MM-DD``），用于按日归档的目录与文件名。"""
    return datetime.now(UTC).date().isoformat()


def parse_event_time(value: str) -> datetime:
    """解析带时区的 ISO 8601 事件时间并归一化为 UTC。"""
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise ValueError("occurred_at 必须是 ISO 8601 时间") from error
    if parsed.tzinfo is None:
        raise ValueError("occurred_at 必须包含时区")
    return parsed.astimezone(UTC)

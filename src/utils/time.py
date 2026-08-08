"""时间处理工具集。

统一使用 UTC ISO 8601 字符串作为数据库时间戳格式。
"""

from datetime import UTC, datetime


def utc_now() -> str:
    """返回当前 UTC 时间的 ISO 格式字符串，用于所有数据库时间戳统一。"""
    return datetime.now(UTC).isoformat()

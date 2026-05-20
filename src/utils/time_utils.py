from __future__ import annotations

from datetime import datetime
from typing import Any


def now_text() -> str:
    """返回当前本地时间的 ISO 8601 文本。

    returns:
        str: 当前本地时间的字符串表示，精确到秒；若转换结果为空则返回空字符串。
    """
    return to_time_text(datetime.now().astimezone()) or ""


def from_epoch_seconds(value: float) -> str:
    """将 Unix 时间戳转换为本地时区的时间文本。

    Args:
        value: 以秒为单位的 Unix 时间戳。

    returns:
        str: 本地时区下的 ISO 8601 时间字符串，精确到秒。
    """
    return datetime.fromtimestamp(value).astimezone().isoformat(timespec="seconds")


def to_time_text(value: Any) -> str | None:
    """将输入值转换为标准化的时间文本。

    Args:
        value: 待转换的时间值，支持 ``datetime`` 对象或 ISO 8601 字符串。

    returns:
        str | None: 转换成功时返回本地时区的 ISO 8601 时间字符串；失败时返回 ``None``。
    """
    dt = parse_time_value(value)
    if dt is None:
        return None
    return dt.isoformat(timespec="seconds")


def to_epoch_seconds(value: Any, default: float | None = None) -> float | None:
    """将输入值转换为 Unix 时间戳。

    Args:
        value: 待转换的时间值，支持 ``datetime`` 对象或 ISO 8601 字符串。
        default: 当输入无法解析为时间时返回的默认值。

    returns:
        float | None: 转换成功时返回以秒为单位的 Unix 时间戳；失败时返回 ``default``。
    """
    dt = parse_time_value(value)
    if dt is None:
        return default
    return dt.timestamp()


def parse_time_value(value: Any) -> datetime | None:
    """解析输入值并统一为带本地时区的 ``datetime`` 对象。

    Args:
        value: 待解析的时间值，可以是 ``datetime``、ISO 8601 字符串或 ``None``。

    returns:
        datetime | None: 解析成功时返回带本地时区的 ``datetime`` 对象；失败时返回 ``None``。
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return _ensure_local_timezone(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        try:
            return _ensure_local_timezone(datetime.fromisoformat(text))
        except ValueError:
            return None
    return None


def _ensure_local_timezone(value: datetime) -> datetime:
    """确保时间对象携带本地时区信息。

    Args:
        value: 需要校正时区信息的 ``datetime`` 对象。

    returns:
        datetime: 带有本地时区信息的 ``datetime`` 对象。
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=datetime.now().astimezone().tzinfo)
    return value.astimezone()

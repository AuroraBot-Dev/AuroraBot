"""动态记忆图前缀的公开线格式。"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from src.contracts.memory_checkpoint import MemoryGraphPrefix

if TYPE_CHECKING:
    from collections.abc import Mapping


def prefix_data(prefix: MemoryGraphPrefix) -> dict[str, Any]:
    """正文与世界记录使用同一份历史坐标。"""
    return {
        "count": prefix.count,
        "cursor": prefix.cursor,
        "recorded_at": prefix.recorded_at.isoformat(),
        "digest": prefix.digest,
    }


def read_prefix(data: Mapping[str, Any]) -> MemoryGraphPrefix:
    """跨进程恢复时仍复用值对象的时间、游标与摘要约束。"""
    return MemoryGraphPrefix(data["count"], data["cursor"], datetime.fromisoformat(data["recorded_at"]), data["digest"])

"""为未来专用记忆 Agent 预留的稳定占位契约。"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class MemoryQuery:
    """记忆查询：查询文本、作用域和返回数量限制。"""

    query: str
    scope: str
    limit: int = 8

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class MemoryResult:
    """记忆查询结果：匹配项元组。"""

    items: tuple[dict[str, Any], ...]


@dataclass(frozen=True, slots=True)
class MemoryProposal:
    """记忆写入提案：内容、来源 Task ID 和重要性。"""

    content: dict[str, Any]
    source_task_id: str
    importance: float = 0.5


@dataclass(frozen=True, slots=True)
class MemoryFailure:
    """记忆操作失败时的标准错误响应。"""

    code: str = "memory.unavailable"
    message: str = "No Memory Agent is configured"

    def to_dict(self) -> dict[str, str]:
        return asdict(self)

"""为未来专用记忆 Agent 预留的稳定占位契约。"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class MemoryQuery:
    """记忆查询：查询文本、作用域和返回数量限制。

    MemoryQuery object::

        {
            "query": "string",
            "scope": "string",
            "limit": 8
        }

    """

    query: str
    scope: str
    limit: int = 8

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class MemoryResult:
    """记忆查询结果：匹配项元组。

    MemoryResult object::

        {
            "items": [{"...": "..."}, ...]
        }

    """

    items: tuple[dict[str, Any], ...]


@dataclass(frozen=True, slots=True)
class MemoryProposal:
    """记忆写入提案：内容、来源 Task ID 和重要性。

    MemoryProposal object::

        {
            "content": {"...": "..."},
            "source_task_id": "UUID",
            "importance": 0.5
        }

    """

    content: dict[str, Any]
    source_task_id: str
    importance: float = 0.5


@dataclass(frozen=True, slots=True)
class MemoryFailure:
    """记忆操作失败时的标准错误响应。

    MemoryFailure object::

        {
            "code": "string",
            "message": "string"
        }

    """

    code: str = "memory.unavailable"
    message: str = "No Memory Agent is configured"

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class MemoryConversation:
    """自动注入上下文的一轮历史对话。"""

    user: str
    assistant: str | None = None


@dataclass(frozen=True, slots=True)
class MemoryContextSnapshot:
    """engine 在 Agent turn 前召回的不可变记忆快照。"""

    recent_conversation: tuple[MemoryConversation, ...] = ()
    related_memories: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class MemoryEntry:
    """engine 提交给自动记忆服务的已完成交互。"""

    task_id: str
    user: str
    assistant: str | None
    created_at: str


class MemoryStore(Protocol):
    """engine 在 turn 前后调用的自动记忆端口。"""

    def recall(self, query: str) -> MemoryContextSnapshot: ...

    def remember(self, entry: MemoryEntry) -> bool: ...

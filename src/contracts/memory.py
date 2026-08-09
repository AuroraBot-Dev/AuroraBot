"""记忆引擎契约：窗口 + 概要（短期）与长期事实。"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class MemoryQuery:
    """按会话读取一次有界记忆快照。"""

    query: str
    scope: str
    fact_limit: int = 4
    max_characters: int = 3000

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class MemoryMessage:
    """记忆窗口中的一条原始消息（短期历史）。"""

    role: str
    content: str
    at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class MemoryContextSnapshot:
    """模型调用前固定下来的三层记忆：概要 + 窗口原文 + 长期事实。"""

    summary: str = ""
    window: tuple[MemoryMessage, ...] = ()
    relevant_facts: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class MemoryEntry:
    """终态 Task 投影到记忆层的最小输入。"""

    task_id: str
    scope: str
    input_summary: str
    outcome_summary: str | None
    created_at: str
    fact_candidates: tuple[str, ...] = ()


class MemoryStore(Protocol):
    """engine 在 Agent turn 前后调用的记忆引擎端口。"""

    async def recall(self, query: MemoryQuery) -> MemoryContextSnapshot: ...

    async def remember(self, entry: MemoryEntry) -> bool: ...

    async def append_turn(self, scope: str, *, role: str, content: str, at: str) -> None: ...

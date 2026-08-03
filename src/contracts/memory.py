"""压缩会话记忆与长期事实的稳定契约。"""

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
class MemoryContextSnapshot:
    """模型调用前固定下来的会话摘要与相关长期事实。"""

    session_summary: str = ""
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
    """engine 在 Root turn 前后调用的压缩记忆端口。"""

    def recall(self, query: MemoryQuery) -> MemoryContextSnapshot: ...

    def remember(self, entry: MemoryEntry) -> bool: ...

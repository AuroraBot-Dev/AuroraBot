"""记忆引擎契约：域内窗口/概要、跨域动态与全局长期事实。"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class MemoryQuery:
    """按会话读取一次有界记忆快照。"""

    query: str
    scope: str
    fact_limit: int = 4
    max_characters: int = 32000
    remote_tail: int = 20
    remote_recency_seconds: float = 21600.0

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
class RemoteMessage:
    """其他会话域窗口尾部的一条消息（跨域动态，带域标签）。"""

    scope: str
    role: str
    content: str
    at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class RemoteSummary:
    """其他会话域最近一次压缩概要（带域标签与更新时间）。"""

    scope: str
    summary: str
    updated_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class MemoryContextSnapshot:
    """模型调用前固定下来的记忆快照：本域概要/窗口 + 跨域动态 + 全局事实。"""

    summary: str = ""
    window: tuple[MemoryMessage, ...] = ()
    remote_summaries: tuple[RemoteSummary, ...] = ()
    remote_window: tuple[RemoteMessage, ...] = ()
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

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> MemoryEntry:
        return cls(**value)


class MemoryStore(Protocol):
    """engine 在 Agent turn 前后调用的记忆引擎端口。"""

    async def recall(self, query: MemoryQuery) -> MemoryContextSnapshot: ...

    async def remember(self, entry: MemoryEntry) -> bool: ...

    async def append_turn(self, scope: str, *, role: str, content: str, at: str) -> None: ...

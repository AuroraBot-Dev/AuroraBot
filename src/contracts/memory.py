"""Stable placeholder contracts for a future dedicated Memory Agent."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class MemoryQuery:
    query: str
    scope: str
    limit: int = 8

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class MemoryResult:
    items: tuple[dict[str, Any], ...]


@dataclass(frozen=True, slots=True)
class MemoryProposal:
    content: dict[str, Any]
    source_task_id: str
    importance: float = 0.5


@dataclass(frozen=True, slots=True)
class MemoryFailure:
    code: str = "memory.unavailable"
    message: str = "No Memory Agent is configured"

    def to_dict(self) -> dict[str, str]:
        return asdict(self)

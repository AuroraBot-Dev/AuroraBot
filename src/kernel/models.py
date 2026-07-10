# ruff: noqa: PLR0913
"""Immutable cognitive event and node contracts."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol
from uuid import uuid4


def utcnow() -> datetime:
    return datetime.now(UTC)


class EventState(StrEnum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    ARCHIVED = "ARCHIVED"
    ERROR = "ERROR"


@dataclass(frozen=True, slots=True)
class CognitiveEvent:
    event_id: str
    event_type: str
    payload: dict[str, object]
    source: str
    session_id: str = "system"
    episode_id: str = ""
    causation_id: str | None = None
    tags: dict[str, object] = field(default_factory=dict)
    created_at: datetime = field(default_factory=utcnow)
    available_at: datetime | None = None
    hop: int = 0
    max_hops: int = 32

    @classmethod
    def create(
        cls,
        event_type: str,
        payload: dict[str, object],
        *,
        source: str,
        session_id: str = "system",
        episode_id: str | None = None,
        causation_id: str | None = None,
        tags: dict[str, object] | None = None,
        available_at: datetime | None = None,
        hop: int = 0,
        max_hops: int = 32,
    ) -> "CognitiveEvent":
        event_id = uuid4().hex
        return cls(
            event_id=event_id,
            event_type=event_type,
            payload=payload,
            source=source,
            session_id=session_id or "system",
            episode_id=episode_id or event_id,
            causation_id=causation_id,
            tags=dict(tags or {}),
            available_at=available_at,
            hop=hop,
            max_hops=max_hops,
        )


@dataclass(frozen=True, slots=True)
class EventOutput:
    event_type: str
    payload: dict[str, object]
    tags: dict[str, object] = field(default_factory=dict)
    available_at: datetime | None = None
    terminal: bool = False


@dataclass(frozen=True, slots=True)
class NodeResult:
    outputs: tuple[EventOutput, ...] = ()
    archive_input: bool = True


@dataclass(frozen=True, slots=True)
class EventSelector:
    event_type: str

    def matches(self, event: CognitiveEvent) -> bool:
        return event.event_type == self.event_type


class CognitiveNode(Protocol):
    async def process(self, context: "NodeContext", event: CognitiveEvent) -> NodeResult: ...


@dataclass(frozen=True, slots=True)
class NodePlugin:
    node_type: str
    inputs: tuple[EventSelector, ...]
    output_types: frozenset[str]
    factory: "NodeFactory"


NodeFactory = Callable[[dict[str, object]], CognitiveNode]


@dataclass(slots=True)
class NodeContext:
    runtime: "CognitiveRuntime"
    node_id: str


from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.kernel.runtime import CognitiveRuntime

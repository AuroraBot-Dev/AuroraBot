"""持久化 Inbox 与语义 Triage 的跨层契约。"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from src.contracts.model import ModelRequest, ModelResult


class TriageAction(StrEnum):
    """Triage 对一个会话事件批次的三种决定。"""

    PROCESS = "process"
    DEFER = "defer"
    DISCARD = "discard"


@dataclass(frozen=True, slots=True)
class TriageLimits:
    """动态防抖、批次和模型调用的硬上界。"""

    model_role: str = "fast"
    quiet_seconds: float = 0.4
    max_wait_seconds: float = 1.5
    defer_seconds: float = 5.0
    max_defer_seconds: float = 60.0
    max_batch_events: int = 24
    max_batch_characters: int = 12000


@dataclass(frozen=True, slots=True)
class InboxEvent:
    """提供给 Triage 的规范事件投影。"""

    event_id: str
    session_id: str
    type: str
    summary: str
    source: dict[str, str]
    data: dict[str, Any]
    created_at: str
    priority: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class TriageBatch:
    """同一会话经防抖聚合的一批事件。"""

    batch_id: str
    session_id: str
    events: tuple[InboxEvent, ...]
    first_received_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "batch_id": self.batch_id,
            "session_id": self.session_id,
            "events": [event.to_dict() for event in self.events],
            "first_received_at": self.first_received_at,
        }


@dataclass(frozen=True, slots=True)
class TriageDecision:
    """Triage 的可审计结构化决定。"""

    action: TriageAction
    summary: str
    reason: str
    defer_seconds: float | None = None
    memory_candidate: str | None = None

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["action"] = self.action.value
        return value


class TriagePolicy(Protocol):
    """由组合根注入 engine 的无状态 Triage 策略。"""

    def request(self, batch: TriageBatch) -> "ModelRequest": ...

    def resolve(self, result: "ModelResult") -> TriageDecision: ...

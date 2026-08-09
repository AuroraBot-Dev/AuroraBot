"""持久化 Inbox、防抖批次与入口 Triage 上下文契约。"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


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

"""Kernel-owned bounded episode state for RFC 0008."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class EpisodeStatus(StrEnum):
    ACTIVE = "ACTIVE"
    WAITING_MODEL = "WAITING_MODEL"
    WAITING_EFFECT = "WAITING_EFFECT"
    COMPLETED = "COMPLETED"
    SILENT = "SILENT"
    CANCELLED = "CANCELLED"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    ERROR = "ERROR"


_TERMINAL_STATUSES = {
    EpisodeStatus.COMPLETED,
    EpisodeStatus.SILENT,
    EpisodeStatus.CANCELLED,
    EpisodeStatus.BUDGET_EXHAUSTED,
    EpisodeStatus.ERROR,
}


@dataclass(slots=True)
class EpisodeSnapshot:
    episode_id: str
    root_record_id: str
    autonomous: bool
    status: EpisodeStatus
    active_node_id: str | None
    round: int
    model_calls: int
    tool_calls: int
    max_model_calls: int
    max_tool_calls: int
    max_duration_seconds: float
    started_at: str
    updated_at: str
    transcript: list[dict[str, Any]] = field(default_factory=list)
    termination_reason: str | None = None

    @property
    def terminal(self) -> bool:
        return self.status in _TERMINAL_STATUSES

    @property
    def elapsed_seconds(self) -> float:
        started = datetime.fromisoformat(self.started_at)
        return max(0.0, (datetime.now(UTC) - started).total_seconds())

    def can_request_model(self) -> bool:
        return (
            not self.terminal
            and self.model_calls < self.max_model_calls
            and self.elapsed_seconds <= self.max_duration_seconds
        )

    def can_request_tool(self) -> bool:
        return (
            not self.terminal
            and self.tool_calls < self.max_tool_calls
            and self.elapsed_seconds <= self.max_duration_seconds
        )

    def touch(self, status: EpisodeStatus, *, node_id: str | None = None, reason: str | None = None) -> None:
        self.status = status
        if node_id is not None:
            self.active_node_id = node_id
        if reason is not None:
            self.termination_reason = reason
        self.updated_at = datetime.now(UTC).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "EpisodeSnapshot":
        raw = dict(value)
        raw["status"] = EpisodeStatus(raw["status"])
        return cls(**raw)

"""Auditable Kernel record types."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from src.kernel.events import AmpEnvelope


class RecordStatus(StrEnum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    ARCHIVED = "ARCHIVED"
    ERROR = "ERROR"


@dataclass(slots=True)
class KernelRecord:
    record_id: str
    amp: dict[str, Any]
    parent_record_id: str | None
    episode_id: str
    producer_node: str | None
    status: RecordStatus
    available_cycle: int
    hop: int
    lease_until: str | None
    error: str | None
    retention: str
    created_at: str
    updated_at: str

    @classmethod
    def from_amp(
        cls,
        amp: AmpEnvelope,
        *,
        available_cycle: int,
        parent: "KernelRecord | None" = None,
        producer_node: str | None = None,
    ) -> "KernelRecord":
        now = datetime.now(UTC).isoformat()
        return cls(
            record_id=str(uuid4()),
            amp=amp.to_dict(),
            parent_record_id=parent.record_id if parent else None,
            episode_id=parent.episode_id if parent else str(uuid4()),
            producer_node=producer_node,
            status=RecordStatus.PENDING,
            available_cycle=available_cycle,
            hop=(parent.hop + 1) if parent else 0,
            lease_until=None,
            error=None,
            retention="standard",
            created_at=now,
            updated_at=now,
        )

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "KernelRecord":
        value = dict(value)
        value["status"] = RecordStatus(value["status"])
        return cls(**value)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def transition(self, status: RecordStatus, *, error: str | None = None) -> None:
        self.status = status
        self.error = error
        self.updated_at = datetime.now(UTC).isoformat()

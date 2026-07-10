"""Shared value types for the AuroraBot kernel."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


def utcnow() -> datetime:
    return datetime.now(UTC)


class FileState(StrEnum):
    CREATED = "CREATED"
    PROCESSING = "PROCESSING"
    ARCHIVED = "ARCHIVED"
    ERROR = "ERROR"


@dataclass(frozen=True, slots=True)
class FileMeta:
    """Metadata for a file in the system.

    Every file is immutable; mutations produce new versions (Copy-on-Write).
    """

    file_id: str
    object_id: str
    version: int = 0
    state: FileState = FileState.CREATED
    owner_id: str | None = None
    write_holder: str | None = None
    read_count: int = 0
    tags: dict[str, Any] = field(default_factory=dict)
    parent_file_id: str | None = None
    previous_file_id: str | None = None
    lease_expire: datetime | None = None
    processing_round: int = 0
    max_rounds: int = 1
    termination_policy: str = "ARCHIVE"
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)
    heartbeat_epoch: int | None = None
    smooth_load: float | None = None
    next_cycle_at: datetime | None = None
    retention_policy: str | None = None


class CasConflict(RuntimeError):
    """Raised when a compare-and-swap update loses a version race."""


class LockDenied(RuntimeError):
    """Raised when a lock or ownership transition is not currently legal."""


class FileNotFoundError_(RuntimeError):
    """Raised when metadata for a file id does not exist."""

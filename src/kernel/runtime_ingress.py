"""AMP ingestion for the Agent Kernel — in-memory and filesystem paths."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any, Protocol

from src.contracts.amp import AmpEnvelope, AmpValidationError
from src.utils.log_utils import get_logger
from src.utils.serialization import read_json

if TYPE_CHECKING:
    from pathlib import Path

    from src.contracts.agent import AgentLimits, AgentProfile, CapabilityCatalogSnapshot, KernelConfiguration
    from src.kernel.store import SQLiteRuntimeStore

logger = get_logger("aurora.kernel")
_RESERVED_TOOL_EVENT = "Tool receipt event types are reserved for internal Runtime use"


class IngressKernel(Protocol):
    configuration: KernelConfiguration
    store: SQLiteRuntimeStore
    _inbox: Path
    _archive: Path
    _profiles: dict[str, AgentProfile]
    _amp_queue: list[Any]

    @property
    def limits(self) -> AgentLimits: ...

    @property
    def capability_catalog(self) -> CapabilityCatalogSnapshot: ...


def ingest_ready(kernel: IngressKernel) -> tuple[str, ...]:
    ingested: list[str] = []
    while kernel._amp_queue:
        amp = kernel._amp_queue.pop(0)
        try:
            _ingest_amp(kernel, amp, ingested)
        except (ValueError, TypeError) as error:
            logger.warning("AMP ingress rejected in-memory reason=%s", error)
    for path in sorted(kernel._inbox.glob("*.json")):
        try:
            amp = AmpEnvelope.parse(read_json(path))
        except (OSError, ValueError, TypeError, AmpValidationError) as error:
            logger.warning("AMP ingress rejected file=%s reason=%s", path.name, error)
            _archive_inbox(kernel, path, "rejected")
            continue
        try:
            _ingest_amp_file(kernel, amp, path, ingested)
        except (ValueError, TypeError) as error:
            logger.warning("AMP ingress rejected file=%s reason=%s", path.name, error)
            _archive_inbox(kernel, path, "rejected")
    return tuple(ingested)


def _ingest_amp(kernel: IngressKernel, amp: AmpEnvelope, ingested: list[str]) -> None:
    """Core AMP ingestion: create Task or ambient Situation. No filesystem side effects."""
    data = amp.payload.data
    if amp.payload.type in {"tool.succeeded", "tool.failed", "tool.unknown"}:
        raise ValueError(_RESERVED_TOOL_EVENT)
    if data.get("ambient") is True:
        situation_id = kernel.store.add_situation(
            amp.header.source["app"],
            amp.payload.type,
            amp.payload.summary,
            amp.to_dict(),
            10 if amp.payload.type == "system.tick" else 100,
            kernel.limits.ambient_ttl_seconds,
        )
        ingested.append(situation_id)
        return
    autonomous = amp.payload.type == "system.tick"
    budget = kernel.configuration.autonomous_budget if autonomous else kernel.configuration.interactive_budget
    task = kernel.store.create_task(
        external_message_id=amp.header.message_id,
        session_id=amp.payload.session_id,
        summary=amp.payload.summary,
        payload={"amp": amp.to_dict()},
        autonomous=autonomous,
        root_profile=kernel.limits.root_profile,
        budget=budget,
        priority=10 if autonomous else 100,
    )
    if task is not None:
        ingested.append(task.task_id)


def _ingest_amp_file(kernel: IngressKernel, amp: AmpEnvelope, path: Path, ingested: list[str]) -> None:
    """Filesystem AMP ingestion with archiving."""
    before = len(ingested)
    _ingest_amp(kernel, amp, ingested)
    if len(ingested) > before:
        _archive_inbox(kernel, path, "accepted")
    else:
        _archive_inbox(kernel, path, "duplicate")


def _archive_inbox(kernel: IngressKernel, source: Path, category: str) -> None:
    destination_dir = kernel._archive / "inbox" / category
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / source.name
    if destination.exists():
        destination = destination_dir / f"{source.stem}-{os.urandom(4).hex()}{source.suffix}"
    source.replace(destination)

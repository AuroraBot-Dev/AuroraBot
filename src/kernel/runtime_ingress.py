"""Filesystem AMP ingestion for the Agent Kernel."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Protocol

from src.contracts.amp import AmpEnvelope, AmpValidationError
from src.kernel.publication import communication_ingress, validate_publication_receipt
from src.utils.log_utils import get_logger
from src.utils.serialization import read_json

if TYPE_CHECKING:
    from pathlib import Path

    from src.contracts.agent import AgentLimits, AgentProfile, CapabilityCatalogSnapshot, KernelConfiguration
    from src.kernel.store import SQLiteRuntimeStore

logger = get_logger("aurora.kernel")


class IngressKernel(Protocol):
    configuration: KernelConfiguration
    store: SQLiteRuntimeStore
    _inbox: Path
    _archive: Path
    _profiles: dict[str, AgentProfile]
    _reply_route_ttl_seconds: float

    @property
    def limits(self) -> AgentLimits: ...

    @property
    def capability_catalog(self) -> CapabilityCatalogSnapshot: ...


def ingest_ready(kernel: IngressKernel) -> tuple[str, ...]:
    ingested: list[str] = []
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


def _ingest_amp_file(kernel: IngressKernel, amp: AmpEnvelope, path: Path, ingested: list[str]) -> None:
    data = amp.payload.data
    if amp.payload.type in {"effect.succeeded", "effect.failed"}:
        matched, message_id = _ingest_effect_receipt(kernel, amp)
        _finish_receipt(kernel, amp, path, (matched, message_id), ingested)
        return
    if amp.payload.type in {
        "publication.succeeded",
        "publication.failed",
        "publication.delivery_unknown",
    }:
        matched, message_id = _ingest_publication_receipt(kernel, amp)
        _finish_receipt(kernel, amp, path, (matched, message_id), ingested)
        return
    audience_ref, reply_grant = communication_ingress(
        event_type=amp.payload.type,
        data=data,
        catalog=kernel.capability_catalog,
        profile=kernel._profiles[kernel.limits.root_profile],
        reply_route_ttl_seconds=kernel._reply_route_ttl_seconds,
    )
    if data.get("ambient") is True:
        situation_id = kernel.store.add_situation(
            amp.header.source["app"],
            amp.payload.type,
            amp.payload.summary,
            amp.to_dict(),
            10 if amp.payload.type == "system.tick" else 100,
            kernel.limits.ambient_ttl_seconds,
            audience_ref if data.get("communication") is not None else _system_situation_audience(amp),
        )
        ingested.append(situation_id)
        _archive_inbox(kernel, path, "accepted")
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
        audience_ref=audience_ref,
        reply_grant=reply_grant,
    )
    _archive_inbox(kernel, path, "accepted" if task is not None else "duplicate")
    if task is not None:
        ingested.append(task.task_id)


def _ingest_effect_receipt(kernel: IngressKernel, amp: AmpEnvelope) -> tuple[bool, str | None]:
    request_id = amp.payload.data.get("request_id")
    if not isinstance(request_id, str):
        return False, None
    return kernel.store.ingest_activity_receipt(
        external_message_id=amp.header.message_id,
        request_id=request_id,
        event_type=amp.payload.type,
        summary=amp.payload.summary,
        payload=amp.payload.data,
    )


def _ingest_publication_receipt(kernel: IngressKernel, amp: AmpEnvelope) -> tuple[bool, str | None]:
    request_id = validate_publication_receipt(amp.payload.type, amp.payload.data)
    return kernel.store.ingest_publication_receipt(
        external_message_id=amp.header.message_id,
        request_id=request_id,
        event_type=amp.payload.type,
        summary=amp.payload.summary,
        payload=amp.payload.data,
    )


def _finish_receipt(
    kernel: IngressKernel,
    amp: AmpEnvelope,
    path: Path,
    outcome: tuple[bool, str | None],
    ingested: list[str],
) -> None:
    matched, message_id = outcome
    if not matched:
        kernel.store.add_situation(
            amp.header.source["app"],
            amp.payload.type,
            amp.payload.summary,
            amp.to_dict(),
            100,
            kernel.limits.ambient_ttl_seconds,
            _system_situation_audience(amp),
        )
    else:
        ingested.append(message_id or amp.header.message_id)
    _archive_inbox(kernel, path, "accepted")


def _system_situation_audience(amp: AmpEnvelope) -> str:
    if amp.payload.type == "system.tick":
        return "system.local"
    return f"{amp.header.source['app']}:system"


def _archive_inbox(kernel: IngressKernel, source: Path, category: str) -> None:
    destination_dir = kernel._archive / "inbox" / category
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / source.name
    if destination.exists():
        destination = destination_dir / f"{source.stem}-{os.urandom(4).hex()}{source.suffix}"
    source.replace(destination)

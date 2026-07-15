"""Kernel ingestion, causal records, graph scheduling, and cycle execution."""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import time
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from jsonschema import ValidationError, validate

from src.ai.contracts import ModelRequest, ModelResult
from src.ai.vnext import ModelGatewayService
from src.kernel.episodes import EpisodeSnapshot, EpisodeStatus
from src.kernel.events import AmpEnvelope, AmpValidationError, new_amp
from src.kernel.node import CognitiveNode, NodeContext
from src.kernel.records import KernelRecord, RecordStatus
from src.localhost.configuration import AuroraConfig, NodeConfig
from src.platform.capabilities import CapabilityCatalogSnapshot, CapabilityDescriptor
from src.utils.log_utils import get_logger
from src.utils.serialization import atomic_write_json, read_json

MAX_HOP = 16
logger = get_logger("aurora.kernel")


@dataclass(frozen=True, slots=True)
class CycleResult:
    cycle: int
    ingested_record_ids: tuple[str, ...]
    scheduled_record_ids: tuple[str, ...]
    failed_record_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class Kernel:
    """The sole owner of the shared event workspace and record state machine."""

    def __init__(
        self, configuration: AuroraConfig, nodes: Mapping[str, CognitiveNode], model_gateway: ModelGatewayService
    ) -> None:
        self.configuration = configuration
        self._nodes = nodes
        self._model_gateway = model_gateway
        self._soul_content = configuration.soul_path.read_text(encoding="utf-8")
        self._workspace = configuration.runtime.workspace
        self._inbox = self._workspace / "inbox"
        self._process = self._workspace / "process"
        self._archive = self._workspace / "archive"
        self._record_process = self._process / "records"
        self._record_archive = self._archive / "records"
        self._episode_process = self._process / "episodes"
        self._episode_archive = self._archive / "episodes"
        for directory in (
            self._inbox,
            self._process,
            self._archive,
            self._record_process,
            self._record_archive,
            self._episode_process,
            self._episode_archive,
        ):
            directory.mkdir(parents=True, exist_ok=True)
        self._state_path = self._process / "kernel-state.json"
        self._lock = asyncio.Lock()
        self._cycle = self._load_cycle()
        configured_capabilities = tuple(
            CapabilityDescriptor(item.id, item.description, item.parameters_schema, item.result_mode)
            for adapter in configuration.adapters
            for item in adapter.capabilities
        )
        self._capability_catalog = CapabilityCatalogSnapshot(configured_capabilities)
        configured = {node.id for node in configuration.nodes}
        if not set(nodes) <= configured or configured != set(nodes):
            raise ValueError("Kernel nodes must exactly match enabled node configuration")
        self._recover_interrupted_model_requests()
        logger.info(
            "kernel initialized workspace=%s cycle=%d nodes=%d capabilities=%d",
            self._workspace,
            self._cycle,
            len(self._nodes),
            len(self._capability_catalog.capabilities),
        )

    @property
    def cycle(self) -> int:
        return self._cycle

    @property
    def capability_catalog(self) -> CapabilityCatalogSnapshot:
        return self._capability_catalog

    def install_capability_catalog(self, catalog: CapabilityCatalogSnapshot) -> None:
        """Install the startup capability snapshot before cognition begins."""
        merged = {item.id: item for item in self._capability_catalog.capabilities}
        merged.update({item.id: item for item in catalog.capabilities})
        self._capability_catalog = CapabilityCatalogSnapshot(tuple(sorted(merged.values(), key=lambda item: item.id)))
        logger.info("capability catalog installed capabilities=%d", len(self._capability_catalog.capabilities))

    def _load_cycle(self) -> int:
        if not self._state_path.exists():
            return 0
        value = read_json(self._state_path)
        if not isinstance(value, dict) or not isinstance(value.get("cycle"), int):
            raise RuntimeError("invalid persisted Kernel state")
        return value["cycle"]

    def _persist_cycle(self) -> None:
        atomic_write_json(self._state_path, {"cycle": self._cycle})

    async def submit_amp(self, amp: AmpEnvelope) -> None:
        """Atomically offer a validated external fact to the next ingress pass."""
        async with self._lock:
            atomic_write_json(self._inbox / f"{amp.header.message_id}.json", amp.to_dict())
            logger.debug(
                "AMP submitted message_id=%s event_type=%s session_id=%s",
                amp.header.message_id,
                amp.payload.type,
                amp.payload.session_id,
            )

    def _record_path(self, record: KernelRecord) -> Path:
        completed = {RecordStatus.ARCHIVED, RecordStatus.ERROR}
        directory = self._record_archive if record.status in completed else self._record_process
        return directory / f"{record.record_id}.json"

    def _save_record(self, record: KernelRecord) -> None:
        destination = self._record_path(record)
        atomic_write_json(destination, record.to_dict())
        other_directory = self._record_process if destination.parent == self._record_archive else self._record_archive
        (other_directory / destination.name).unlink(missing_ok=True)

    def _episode_path(self, episode: EpisodeSnapshot) -> Path:
        directory = self._episode_archive if episode.terminal else self._episode_process
        return directory / f"{episode.episode_id}.json"

    def _save_episode(self, episode: EpisodeSnapshot) -> None:
        destination = self._episode_path(episode)
        atomic_write_json(destination, episode.to_dict())
        other = self._episode_process if destination.parent == self._episode_archive else self._episode_archive
        (other / destination.name).unlink(missing_ok=True)

    def get_episode(self, episode_id: str) -> EpisodeSnapshot | None:
        for directory in (self._episode_process, self._episode_archive):
            path = directory / f"{episode_id}.json"
            if path.exists():
                value = read_json(path)
                if isinstance(value, dict):
                    return EpisodeSnapshot.from_dict(value)
        return None

    def episodes(self) -> tuple[EpisodeSnapshot, ...]:
        result: list[EpisodeSnapshot] = []
        for directory in (self._episode_process, self._episode_archive):
            for path in sorted(directory.glob("*.json")):
                value = read_json(path)
                if isinstance(value, dict):
                    result.append(EpisodeSnapshot.from_dict(value))
        return tuple(result)

    def _create_episode(self, record: KernelRecord, *, autonomous: bool) -> EpisodeSnapshot:
        budget = (
            self.configuration.runtime.autonomous_budget
            if autonomous
            else self.configuration.runtime.interactive_budget
        )
        now = datetime.now(UTC).isoformat()
        episode = EpisodeSnapshot(
            episode_id=record.episode_id,
            root_record_id=record.record_id,
            autonomous=autonomous,
            status=EpisodeStatus.ACTIVE,
            active_node_id=None,
            round=0,
            model_calls=0,
            tool_calls=0,
            max_model_calls=budget.max_model_calls,
            max_tool_calls=budget.max_tool_calls,
            max_duration_seconds=budget.max_duration_seconds,
            started_at=now,
            updated_at=now,
            transcript=[{"kind": "event", "record_id": record.record_id, "amp": record.amp}],
        )
        self._save_episode(episode)
        logger.debug(
            "episode created episode_id=%s record_id=%s autonomous=%s model_budget=%d "
            "tool_budget=%d duration_budget_s=%.1f",
            episode.episode_id,
            record.record_id,
            autonomous,
            episode.max_model_calls,
            episode.max_tool_calls,
            episode.max_duration_seconds,
        )
        return episode

    def _append_episode_item(self, episode_id: str, item: dict[str, Any]) -> EpisodeSnapshot | None:
        episode = self.get_episode(episode_id)
        if episode is None:
            return None
        episode.transcript.append(item)
        episode.updated_at = datetime.now(UTC).isoformat()
        self._save_episode(episode)
        return episode

    def _end_episode(self, episode_id: str, status: EpisodeStatus, reason: str) -> None:
        episode = self.get_episode(episode_id)
        if episode is None or episode.terminal:
            return
        episode.touch(status, reason=reason)
        self._save_episode(episode)
        logger.info(
            "episode ended episode_id=%s status=%s reason=%s rounds=%d model_calls=%d tool_calls=%d",
            episode.episode_id,
            status,
            reason,
            episode.round,
            episode.model_calls,
            episode.tool_calls,
        )

    def _records(self) -> list[KernelRecord]:
        records: list[KernelRecord] = []
        for directory in (self._record_process, self._record_archive):
            for path in sorted(directory.glob("*.json")):
                try:
                    value = read_json(path)
                    if not isinstance(value, dict):
                        raise ValueError("record root is not an object")
                    records.append(KernelRecord.from_dict(value))
                except (OSError, ValueError, KeyError, TypeError) as error:
                    raise RuntimeError(f"invalid Kernel record at {path}: {error}") from error
        return records

    def get_record(self, record_id: str) -> KernelRecord | None:
        for directory in (self._record_process, self._record_archive):
            path = directory / f"{record_id}.json"
            if path.exists():
                value = read_json(path)
                if isinstance(value, dict):
                    return KernelRecord.from_dict(value)
        return None

    def has_cycle_work(self) -> bool:
        if any(self._inbox.glob("*.json")):
            return True
        return any(
            record.status == RecordStatus.PENDING
            and record.available_cycle <= self._cycle + 1
            and AmpEnvelope.parse(record.amp).payload.type not in {"model.requested", "effect.requested"}
            for record in self._records()
        )

    def has_pending_model_request(self) -> bool:
        return any(
            record.status == RecordStatus.PENDING and AmpEnvelope.parse(record.amp).payload.type == "model.requested"
            for record in self._records()
        )

    def _archive_inbox_file(self, source: Path, category: str) -> None:
        destination_dir = self._archive / "inbox" / category
        destination_dir.mkdir(parents=True, exist_ok=True)
        destination = destination_dir / source.name
        if destination.exists():
            destination = destination_dir / f"{source.stem}-{os.urandom(4).hex()}{source.suffix}"
        source.replace(destination)

    def _write_ingress_error(self, source: Path, error: str) -> KernelRecord:
        rejected_dir = self._archive / "inbox" / "rejected"
        rejected_dir.mkdir(parents=True, exist_ok=True)
        rejected = rejected_dir / source.name
        if source.exists():
            source.replace(rejected)
        amp = new_amp(
            event_type="system.ingress_rejected",
            session_id="kernel",
            summary="Rejected invalid AMP ingress",
            data={"file": rejected.name, "reason": error},
            source_app="kernel",
            source_instance="ingress",
        )
        record = KernelRecord.from_amp(amp, available_cycle=self._cycle)
        record.transition(RecordStatus.ERROR, error=error)
        self._save_record(record)
        logger.warning(
            "AMP ingress rejected record_id=%s file=%s reason=%s",
            record.record_id,
            rejected.name,
            error,
        )
        return record

    def ingest_ready(self) -> tuple[str, ...]:
        """Take every completed inbox JSON file into the current cycle."""
        existing_message_ids = {
            AmpEnvelope.parse(record.amp).header.message_id for record in self._records() if record.amp.get("header")
        }
        ingested: list[str] = []
        for path in sorted(self._inbox.glob("*.json")):
            try:
                raw = read_json(path)
                amp = AmpEnvelope.parse(raw)
            except (OSError, ValueError, TypeError, AmpValidationError) as error:
                self._write_ingress_error(path, str(error))
                continue
            if amp.header.message_id in existing_message_ids:
                self._archive_inbox_file(path, "duplicate")
                logger.warning("duplicate AMP ignored message_id=%s file=%s", amp.header.message_id, path.name)
                continue
            parent = self._effect_parent(amp)
            autonomous = amp.payload.type == "system.tick"
            resume_node_id = self._receipt_resume_node(amp, parent)
            record = KernelRecord.from_amp(
                amp,
                available_cycle=self._cycle,
                parent=parent,
                resume_node_id=resume_node_id,
                priority=10 if autonomous else 100,
                episode_round=parent.episode_round if parent else 0,
            )
            self._save_record(record)
            if parent is None:
                self._create_episode(record, autonomous=autonomous)
            else:
                self._append_episode_item(
                    record.episode_id,
                    {"kind": "effect_receipt", "record_id": record.record_id, "amp": record.amp},
                )
                if amp.payload.type == "effect.succeeded" and resume_node_id is None:
                    self._end_episode(record.episode_id, EpisodeStatus.COMPLETED, "terminal_effect_succeeded")
            self._archive_inbox_file(path, "accepted")
            existing_message_ids.add(amp.header.message_id)
            ingested.append(record.record_id)
            logger.debug(
                "AMP ingested cycle=%d record_id=%s episode_id=%s event_type=%s parent_record_id=%s priority=%d",
                self._cycle,
                record.record_id,
                record.episode_id,
                amp.payload.type,
                record.parent_record_id,
                record.priority,
            )
        return tuple(ingested)

    def _receipt_resume_node(self, amp: AmpEnvelope, parent: KernelRecord | None) -> str | None:
        if parent is None or amp.payload.type not in {"effect.succeeded", "effect.failed"}:
            return None
        if amp.payload.type == "effect.failed":
            return parent.resume_node_id
        capability = amp.payload.data.get("capability")
        descriptor = self._capability_catalog.by_id.get(capability) if isinstance(capability, str) else None
        if descriptor is not None and descriptor.result_mode == "terminal":
            return None
        return parent.resume_node_id

    def _effect_parent(self, amp: AmpEnvelope) -> KernelRecord | None:
        if amp.payload.type not in {"effect.succeeded", "effect.failed"}:
            return None
        request_id = amp.payload.data.get("request_id")
        if not isinstance(request_id, str):
            return None
        for candidate in self._records():
            candidate_amp = AmpEnvelope.parse(candidate.amp)
            is_request = candidate_amp.payload.type == "effect.requested"
            if is_request and candidate_amp.payload.data.get("request_id") == request_id:
                return candidate
        return None

    def publish_from_node(
        self,
        parent: KernelRecord,
        node_id: str,
        event_type: str,
        data: dict[str, Any],
        summary: str,
        resume_node_id: str | None = None,
    ) -> KernelRecord:
        """Create a declared child fact that cannot run before the next cycle."""
        node = self._node_configuration(node_id)
        if event_type not in node.outputs:
            raise PermissionError(f"node {node_id} cannot publish {event_type}")
        if parent.hop >= MAX_HOP:
            raise RuntimeError(f"causal hop limit {MAX_HOP} reached")
        if event_type == "effect.requested":
            if not isinstance(data.get("capability"), str) or not isinstance(data.get("parameters"), dict):
                raise ValueError("effect.requested requires capability and parameters")
            data = {**data, "request_id": str(uuid4())}
            capability = data["capability"]
            assert isinstance(capability, str)
            descriptor = self._capability_catalog.by_id.get(capability)
            if descriptor is None:
                raise ValueError(f"unknown effect capability {capability}")
            try:
                validate(data["parameters"], descriptor.parameters_schema)
            except ValidationError as error:
                raise ValueError(f"effect parameters do not match {capability} schema: {error.message}") from error
            episode = self.get_episode(parent.episode_id)
            if episode is not None:
                if not episode.can_request_tool():
                    self._end_episode(parent.episode_id, EpisodeStatus.BUDGET_EXHAUSTED, "tool_budget_exhausted")
                    raise RuntimeError("episode tool budget exhausted")
                episode.tool_calls += 1
                episode.touch(EpisodeStatus.WAITING_EFFECT, node_id=node_id)
                self._save_episode(episode)
        amp = new_amp(
            event_type=event_type,
            session_id=AmpEnvelope.parse(parent.amp).payload.session_id,
            summary=summary,
            data=data,
            source_app="kernel.node",
            source_instance=node_id,
        )
        child = KernelRecord.from_amp(
            amp,
            available_cycle=self._cycle + 1,
            parent=parent,
            producer_node=node_id,
            resume_node_id=resume_node_id,
            priority=parent.priority,
            episode_round=parent.episode_round,
        )
        self._save_record(child)
        self._append_episode_item(
            child.episode_id,
            {"kind": event_type, "record_id": child.record_id, "amp": child.amp},
        )
        logger.debug(
            "node event published cycle=%d record_id=%s parent_record_id=%s episode_id=%s "
            "node_id=%s event_type=%s resume_node_id=%s",
            self._cycle,
            child.record_id,
            parent.record_id,
            child.episode_id,
            node_id,
            event_type,
            resume_node_id,
        )
        return child

    def _node_configuration(self, node_id: str) -> NodeConfig:
        for node in self.configuration.nodes:
            if node.id == node_id:
                return node
        raise KeyError(f"unknown node {node_id}")

    async def run_cycle(self) -> CycleResult:
        """Consume only records ready at cycle start; child records wait until the next cycle."""
        async with self._lock:
            return await self._run_cycle()

    async def _run_cycle(self) -> CycleResult:
        started = time.monotonic()
        self._cycle += 1
        self._persist_cycle()
        ingested = self.ingest_ready()
        ready = [
            record
            for record in self._records()
            if record.status == RecordStatus.PENDING
            and record.available_cycle <= self._cycle
            and AmpEnvelope.parse(record.amp).payload.type not in {"model.requested", "effect.requested"}
        ]
        ready.sort(key=lambda item: (-item.priority, item.created_at, item.record_id))
        logger.debug("cycle started cycle=%d ingested=%d ready=%d", self._cycle, len(ingested), len(ready))
        scheduled: list[str] = []
        failed: list[str] = []
        for record in ready:
            event_type = AmpEnvelope.parse(record.amp).payload.type
            configured_targets = self.configuration.edges.get(event_type, ())
            targets = tuple(
                record.resume_node_id if target == "@continuation" else target
                for target in configured_targets
                if target != "@continuation" or record.resume_node_id is not None
            )
            if not targets:
                record.transition(RecordStatus.ARCHIVED)
                self._save_record(record)
                continue
            record.transition(RecordStatus.PROCESSING)
            self._save_record(record)
            try:
                for target in targets:
                    if target is None:
                        continue
                    node_config = self._node_configuration(target)
                    episode = self.get_episode(record.episode_id)
                    if episode is not None and episode.terminal:
                        continue
                    advances = (event_type, target) in self.configuration.advancing_edges or (
                        event_type,
                        "@continuation",
                    ) in self.configuration.advancing_edges
                    if advances:
                        record.episode_round += 1
                        if episode is not None:
                            episode.round += 1
                            episode.touch(EpisodeStatus.ACTIVE, node_id=target)
                            self._save_episode(episode)
                    logger.debug(
                        "node scheduled cycle=%d record_id=%s episode_id=%s event_type=%s "
                        "node_id=%s round=%d advances_round=%s",
                        self._cycle,
                        record.record_id,
                        record.episode_id,
                        event_type,
                        target,
                        record.episode_round,
                        advances,
                    )
                    descriptors = [
                        descriptor
                        for capability in sorted(node_config.capabilities)
                        if (descriptor := self._capability_catalog.by_id.get(capability)) is not None
                    ]
                    context = NodeContext(
                        record=record,
                        soul_hash=self.configuration.soul_hash,
                        soul_content=self._soul_content,
                        configuration_snapshot={
                            "node_id": target,
                            "model_roles": sorted(node_config.model_roles),
                            "capabilities": sorted(node_config.capabilities),
                            "capability_descriptors": [descriptor.to_dict() for descriptor in descriptors],
                        },
                        allowed_outputs=node_config.outputs,
                        allowed_capabilities=node_config.capabilities,
                        episode_snapshot=episode.to_dict() if episode is not None else {},
                        _publisher=self,
                        _node_id=target,
                    )
                    await self._nodes[target].execute(context)
                record.transition(RecordStatus.ARCHIVED)
                self._save_record(record)
                scheduled.append(record.record_id)
            except Exception as error:
                record.transition(RecordStatus.ERROR, error=f"{type(error).__name__}: {error}")
                self._save_record(record)
                failed.append(record.record_id)
                logger.log(
                    logging.ERROR,
                    "node execution failed cycle=%d record_id=%s episode_id=%s event_type=%s error_type=%s",
                    self._cycle,
                    record.record_id,
                    record.episode_id,
                    event_type,
                    type(error).__name__,
                )
        result = CycleResult(self._cycle, tuple(ingested), tuple(scheduled), tuple(failed))
        logger.debug(
            "cycle completed cycle=%d ingested=%d scheduled=%d failed=%d duration_ms=%.1f",
            self._cycle,
            len(ingested),
            len(scheduled),
            len(failed),
            (time.monotonic() - started) * 1000,
        )
        return result

    def defer_model_from_node(self, parent: KernelRecord, node_id: str, request: ModelRequest) -> KernelRecord:
        """Publish a model request for the out-of-cycle dispatcher."""
        episode = self.get_episode(parent.episode_id)
        if episode is not None:
            if not episode.can_request_model():
                self._end_episode(parent.episode_id, EpisodeStatus.BUDGET_EXHAUSTED, "model_budget_exhausted")
                raise RuntimeError("episode model budget exhausted")
            episode.model_calls += 1
            episode.touch(EpisodeStatus.WAITING_MODEL, node_id=node_id)
            self._save_episode(episode)
        record = self._create_model_record(
            parent,
            node_id,
            "model.requested",
            request.to_dict(),
            resume_node_id=node_id,
        )
        self._append_episode_item(
            parent.episode_id,
            {"kind": "model.requested", "record_id": record.record_id, "request": request.to_dict()},
        )
        logger.debug(
            "model request queued record_id=%s parent_record_id=%s episode_id=%s node_id=%s "
            "model_role=%s endpoint=%s tools=%d",
            record.record_id,
            parent.record_id,
            record.episode_id,
            node_id,
            request.role,
            request.response_mode,
            len(request.tools),
        )
        return record

    def end_episode_from_node(self, parent: KernelRecord, node_id: str, outcome: str, reason: str) -> KernelRecord:
        status = EpisodeStatus.SILENT if outcome == "silent" else EpisodeStatus.COMPLETED
        if outcome == "cancelled":
            status = EpisodeStatus.CANCELLED
        elif outcome == "error":
            status = EpisodeStatus.ERROR
        self._end_episode(parent.episode_id, status, reason)
        return self.publish_from_node(
            parent,
            node_id,
            "episode.ended",
            {"outcome": outcome, "reason": reason},
            f"Episode ended: {outcome}",
        )

    async def claim_model_request(self) -> KernelRecord | None:
        async with self._lock:
            candidates = [
                record
                for record in self._records()
                if record.status == RecordStatus.PENDING
                and AmpEnvelope.parse(record.amp).payload.type == "model.requested"
            ]
            candidates.sort(key=lambda item: (-item.priority, item.created_at, item.record_id))
            if not candidates:
                return None
            record = candidates[0]
            record.transition(RecordStatus.PROCESSING)
            self._save_record(record)
            amp = AmpEnvelope.parse(record.amp)
            logger.debug(
                "model request claimed record_id=%s episode_id=%s model_role=%s priority=%d",
                record.record_id,
                record.episode_id,
                amp.payload.data.get("role"),
                record.priority,
            )
            return record

    async def execute_model_request(self, record: KernelRecord) -> KernelRecord:
        """Execute a claimed request without holding the Kernel cycle lock."""
        amp = AmpEnvelope.parse(record.amp)
        started = time.monotonic()
        model_role = str(amp.payload.data.get("role", "unknown"))
        logger.debug(
            "model request started record_id=%s episode_id=%s model_role=%s",
            record.record_id,
            record.episode_id,
            model_role,
        )
        try:
            request = ModelRequest.from_dict(amp.payload.data)
            result = await self._model_gateway.complete(request)
        except Exception as error:
            async with self._lock:
                message = f"{type(error).__name__}: {error}"
                record.transition(RecordStatus.ERROR, error=message)
                self._save_record(record)
                failed = self._create_model_record(
                    record,
                    record.producer_node or record.resume_node_id or "kernel",
                    "model.failed",
                    {"error": message},
                    resume_node_id=record.resume_node_id,
                )
                self._append_episode_item(
                    record.episode_id,
                    {"kind": "model.failed", "record_id": failed.record_id, "error": message},
                )
                logger.warning(
                    "model request failed record_id=%s episode_id=%s model_role=%s duration_ms=%.1f error_type=%s",
                    record.record_id,
                    record.episode_id,
                    model_role,
                    (time.monotonic() - started) * 1000,
                    type(error).__name__,
                )
                return failed
        async with self._lock:
            record.transition(RecordStatus.ARCHIVED)
            self._save_record(record)
            completed = self._create_model_record(
                record,
                record.producer_node or record.resume_node_id or "kernel",
                "model.completed",
                result.to_dict(),
                resume_node_id=record.resume_node_id,
            )
            self._append_episode_item(
                record.episode_id,
                {"kind": "model.completed", "record_id": completed.record_id, "result": result.to_dict()},
            )
            logger.info(
                "model request completed record_id=%s completed_record_id=%s episode_id=%s model_role=%s "
                "model=%s prompt_tokens=%d completion_tokens=%d cost_usd=%.6f tool_calls=%d "
                "finish_reason=%s duration_ms=%.1f",
                record.record_id,
                completed.record_id,
                record.episode_id,
                model_role,
                result.model,
                result.usage.prompt_tokens,
                result.usage.completion_tokens,
                result.cost_usd,
                len(result.tool_calls),
                result.finish_reason,
                (time.monotonic() - started) * 1000,
            )
            return completed

    def cancel_model_request(self, record: KernelRecord, reason: str) -> KernelRecord:
        message = f"cancelled:{reason}"
        record.transition(RecordStatus.ERROR, error=message)
        self._save_record(record)
        failed = self._create_model_record(
            record,
            record.producer_node or record.resume_node_id or "kernel",
            "model.failed",
            {"error": message},
            resume_node_id=record.resume_node_id,
        )
        status = EpisodeStatus.BUDGET_EXHAUSTED if reason == "autonomous_daily_budget" else EpisodeStatus.CANCELLED
        self._end_episode(record.episode_id, status, reason)
        logger.warning(
            "model request cancelled record_id=%s episode_id=%s reason=%s",
            record.record_id,
            record.episode_id,
            reason,
        )
        return failed

    def _recover_interrupted_model_requests(self) -> None:
        for record in self._records():
            if record.status != RecordStatus.PROCESSING:
                continue
            amp = AmpEnvelope.parse(record.amp)
            if amp.payload.type != "model.requested":
                continue
            message = "interrupted_by_restart"
            record.transition(RecordStatus.ERROR, error=message)
            self._save_record(record)
            self._create_model_record(
                record,
                record.producer_node or record.resume_node_id or "kernel",
                "model.failed",
                {"error": message},
                resume_node_id=record.resume_node_id,
            )
            logger.warning(
                "interrupted model request recovered record_id=%s episode_id=%s resume_node_id=%s reason=%s",
                record.record_id,
                record.episode_id,
                record.resume_node_id,
                message,
            )

    async def request_model_from_node(self, parent: KernelRecord, node_id: str, request: ModelRequest) -> ModelResult:
        """Run an authorized model capability and retain request/outcome audit records."""
        request_record = self._create_model_record(parent, node_id, "model.requested", request.to_dict())
        try:
            result = await self._model_gateway.complete(request)
        except Exception as error:
            request_record.transition(RecordStatus.ERROR, error=f"{type(error).__name__}: {error}")
            self._save_record(request_record)
            failed = self._create_model_record(
                request_record,
                node_id,
                "model.failed",
                {"error": f"{type(error).__name__}: {error}"},
            )
            failed.transition(RecordStatus.ERROR, error=f"{type(error).__name__}: {error}")
            self._save_record(failed)
            raise
        request_record.transition(RecordStatus.ARCHIVED)
        self._save_record(request_record)
        self._create_model_record(request_record, node_id, "model.completed", result.to_dict())
        return result

    def _create_model_record(
        self,
        parent: KernelRecord,
        node_id: str,
        event_type: str,
        data: dict[str, Any],
        *,
        resume_node_id: str | None = None,
    ) -> KernelRecord:
        amp = new_amp(
            event_type=event_type,
            session_id=AmpEnvelope.parse(parent.amp).payload.session_id,
            summary=event_type,
            data=data,
            source_app="kernel.model",
            source_instance=node_id,
        )
        record = KernelRecord.from_amp(
            amp,
            available_cycle=self._cycle + 1,
            parent=parent,
            producer_node=node_id,
            resume_node_id=resume_node_id,
            priority=parent.priority,
            episode_round=parent.episode_round,
        )
        self._save_record(record)
        return record

    async def claim_effect_requests(self, capabilities: frozenset[str]) -> tuple[KernelRecord, ...]:
        """Atomically reserve pending, authorized effects for one Platform adapter."""
        async with self._lock:
            return self._claim_effect_requests(capabilities)

    def _claim_effect_requests(self, capabilities: frozenset[str]) -> tuple[KernelRecord, ...]:
        claimed: list[KernelRecord] = []
        for record in self._records():
            if record.status != RecordStatus.PENDING:
                continue
            amp = AmpEnvelope.parse(record.amp)
            if amp.payload.type != "effect.requested":
                continue
            capability = amp.payload.data.get("capability")
            if capability not in capabilities:
                continue
            record.transition(RecordStatus.PROCESSING)
            self._save_record(record)
            claimed.append(record)
            logger.debug(
                "effect request claimed record_id=%s episode_id=%s capability=%s",
                record.record_id,
                record.episode_id,
                capability,
            )
        return tuple(claimed)

    def complete_effect(self, record: KernelRecord, *, error: str | None = None) -> None:
        """Close the source request after Platform has emitted its separate receipt."""
        record.transition(RecordStatus.ERROR if error else RecordStatus.ARCHIVED, error=error)
        self._save_record(record)
        amp = AmpEnvelope.parse(record.amp)
        logger.debug(
            "effect request completed record_id=%s episode_id=%s capability=%s status=%s failed=%s",
            record.record_id,
            record.episode_id,
            amp.payload.data.get("capability"),
            record.status,
            error is not None,
        )

    def reset_workspace_for_tests(self) -> None:
        """Remove only this configured workspace; intended for test fixtures."""
        shutil.rmtree(self._workspace)

"""Kernel ingestion, causal records, graph scheduling, and cycle execution."""

from __future__ import annotations

import asyncio
import os
import shutil
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from jsonschema import ValidationError, validate

from src.ai.contracts import ModelRequest, ModelResult
from src.ai.vnext import ModelGatewayService
from src.kernel.events import AmpEnvelope, AmpValidationError, new_amp
from src.kernel.node import CognitiveNode, NodeContext
from src.kernel.records import KernelRecord, RecordStatus
from src.localhost.configuration import AuroraConfig, NodeConfig
from src.utils.jsonio import atomic_write_json, read_json

MAX_HOP = 16


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
        for directory in (self._inbox, self._process, self._archive, self._record_process, self._record_archive):
            directory.mkdir(parents=True, exist_ok=True)
        self._state_path = self._process / "kernel-state.json"
        self._lock = asyncio.Lock()
        self._cycle = self._load_cycle()
        configured = {node.id for node in configuration.nodes}
        if not set(nodes) <= configured or configured != set(nodes):
            raise ValueError("Kernel nodes must exactly match enabled node configuration")

    @property
    def cycle(self) -> int:
        return self._cycle

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

    def _record_path(self, record: KernelRecord) -> Path:
        completed = {RecordStatus.ARCHIVED, RecordStatus.ERROR}
        directory = self._record_archive if record.status in completed else self._record_process
        return directory / f"{record.record_id}.json"

    def _save_record(self, record: KernelRecord) -> None:
        destination = self._record_path(record)
        atomic_write_json(destination, record.to_dict())
        other_directory = self._record_process if destination.parent == self._record_archive else self._record_archive
        (other_directory / destination.name).unlink(missing_ok=True)

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
                continue
            parent = self._effect_parent(amp)
            record = KernelRecord.from_amp(amp, available_cycle=self._cycle, parent=parent)
            self._save_record(record)
            self._archive_inbox_file(path, "accepted")
            existing_message_ids.add(amp.header.message_id)
            ingested.append(record.record_id)
        return tuple(ingested)

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
            descriptor = self.configuration.capability_definitions.get(capability)
            if descriptor is None:
                raise ValueError(f"unknown effect capability {capability}")
            try:
                validate(data["parameters"], descriptor.parameters_schema)
            except ValidationError as error:
                raise ValueError(f"effect parameters do not match {capability} schema: {error.message}") from error
        amp = new_amp(
            event_type=event_type,
            session_id=AmpEnvelope.parse(parent.amp).payload.session_id,
            summary=summary,
            data=data,
            source_app="kernel.node",
            source_instance=node_id,
        )
        child = KernelRecord.from_amp(amp, available_cycle=self._cycle + 1, parent=parent, producer_node=node_id)
        self._save_record(child)
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
        self._cycle += 1
        self._persist_cycle()
        ingested = self.ingest_ready()
        ready = [
            record
            for record in self._records()
            if record.status == RecordStatus.PENDING and record.available_cycle <= self._cycle
        ]
        scheduled: list[str] = []
        failed: list[str] = []
        for record in ready:
            event_type = AmpEnvelope.parse(record.amp).payload.type
            targets = self.configuration.edges.get(event_type, ())
            if not targets:
                record.transition(RecordStatus.ARCHIVED)
                self._save_record(record)
                continue
            record.transition(RecordStatus.PROCESSING)
            self._save_record(record)
            try:
                for target in targets:
                    node_config = self._node_configuration(target)
                    context = NodeContext(
                        record=record,
                        soul_hash=self.configuration.soul_hash,
                        soul_content=self._soul_content,
                        configuration_snapshot={
                            "node_id": target,
                            "model_roles": sorted(node_config.model_roles),
                            "capabilities": sorted(node_config.capabilities),
                            "capability_descriptors": [
                                {
                                    "id": capability,
                                    "parameters_schema": self.configuration.capability_definitions[
                                        capability
                                    ].parameters_schema,
                                }
                                for capability in sorted(node_config.capabilities)
                            ],
                        },
                        allowed_outputs=node_config.outputs,
                        allowed_capabilities=node_config.capabilities,
                        _publisher=self,
                        _node_id=target,
                    )
                    await self._nodes[target].execute(context)
                record.transition(RecordStatus.ARCHIVED)
                self._save_record(record)
                scheduled.append(record.record_id)
            except Exception as error:  # noqa: BLE001 - node failures must become auditable records.
                record.transition(RecordStatus.ERROR, error=f"{type(error).__name__}: {error}")
                self._save_record(record)
                failed.append(record.record_id)
        return CycleResult(self._cycle, tuple(ingested), tuple(scheduled), tuple(failed))

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
        self, parent: KernelRecord, node_id: str, event_type: str, data: dict[str, Any]
    ) -> KernelRecord:
        amp = new_amp(
            event_type=event_type,
            session_id=AmpEnvelope.parse(parent.amp).payload.session_id,
            summary=event_type,
            data=data,
            source_app="kernel.model",
            source_instance=node_id,
        )
        record = KernelRecord.from_amp(amp, available_cycle=self._cycle + 1, parent=parent, producer_node=node_id)
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
        return tuple(claimed)

    def complete_effect(self, record: KernelRecord, *, error: str | None = None) -> None:
        """Close the source request after Platform has emitted its separate receipt."""
        record.transition(RecordStatus.ERROR if error else RecordStatus.ARCHIVED, error=error)
        self._save_record(record)

    def reset_workspace_for_tests(self) -> None:
        """Remove only this configured workspace; intended for test fixtures."""
        shutil.rmtree(self._workspace)

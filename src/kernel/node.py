"""The restricted interface Kernel supplies to cognitive nodes."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from src.ai.contracts import ModelContinuation, ModelRequest, ModelResult
from src.kernel.events import AmpEnvelope
from src.kernel.records import KernelRecord


class NodeContractError(PermissionError):
    """Raised when a node exceeds its declared event or capability contract."""


class EventPublisher(Protocol):
    def publish_from_node(
        self,
        parent: KernelRecord,
        node_id: str,
        event_type: str,
        data: dict[str, Any],
        summary: str,
        resume_node_id: str | None = None,
    ) -> KernelRecord: ...

    async def request_model_from_node(
        self, parent: KernelRecord, node_id: str, request: ModelRequest
    ) -> ModelResult: ...

    def defer_model_from_node(self, parent: KernelRecord, node_id: str, request: ModelRequest) -> KernelRecord: ...

    def end_episode_from_node(self, parent: KernelRecord, node_id: str, outcome: str, reason: str) -> KernelRecord: ...


@dataclass(frozen=True, slots=True)
class NodeContext:
    """Read-only input and controlled publication surface for one node invocation."""

    record: KernelRecord
    soul_hash: str
    soul_content: str
    configuration_snapshot: dict[str, Any]
    allowed_outputs: frozenset[str]
    allowed_capabilities: frozenset[str]
    episode_snapshot: dict[str, Any]
    _publisher: EventPublisher = field(repr=False)
    _node_id: str = field(repr=False)

    @property
    def amp(self) -> AmpEnvelope:
        return AmpEnvelope.parse(self.record.amp)

    def request_effect(
        self,
        capability: str,
        parameters: dict[str, Any],
        summary: str,
        *,
        tool_call_id: str | None = None,
        continuation: ModelContinuation | None = None,
    ) -> KernelRecord:
        if "effect.requested" not in self.allowed_outputs:
            raise NodeContractError(f"{self._node_id} cannot publish effect.requested")
        if capability not in self.allowed_capabilities:
            raise NodeContractError(f"{self._node_id} cannot request {capability}")
        data: dict[str, Any] = {"capability": capability, "parameters": parameters}
        if tool_call_id is not None:
            data["tool_call_id"] = tool_call_id
        if continuation is not None:
            data["model_continuation"] = continuation.to_dict()
        return self._publisher.publish_from_node(
            self.record,
            self._node_id,
            "effect.requested",
            data,
            summary,
            resume_node_id=self._node_id,
        )

    async def request_model(self, request: ModelRequest) -> ModelResult:
        """Request one declared model role through Kernel's auditable capability boundary."""
        if request.role not in self.configuration_snapshot["model_roles"]:
            raise NodeContractError(f"{self._node_id} cannot request model role {request.role}")
        return await self._publisher.request_model_from_node(self.record, self._node_id, request)

    def defer_model(self, request: ModelRequest) -> KernelRecord:
        """Publish an asynchronous model request and end this node invocation."""
        if request.role not in self.configuration_snapshot["model_roles"]:
            raise NodeContractError(f"{self._node_id} cannot request model role {request.role}")
        return self._publisher.defer_model_from_node(self.record, self._node_id, request)

    def finish_episode(self, outcome: str, reason: str) -> KernelRecord:
        if "episode.ended" not in self.allowed_outputs:
            raise NodeContractError(f"{self._node_id} cannot publish episode.ended")
        return self._publisher.end_episode_from_node(self.record, self._node_id, outcome, reason)

    def publish_event(self, event_type: str, data: dict[str, Any], summary: str) -> KernelRecord:
        if event_type not in self.allowed_outputs:
            raise NodeContractError(f"{self._node_id} cannot publish {event_type}")
        return self._publisher.publish_from_node(self.record, self._node_id, event_type, data, summary)


class CognitiveNode(Protocol):
    """A self-contained cognitive node with no Platform or workspace access."""

    async def execute(self, context: NodeContext) -> None: ...

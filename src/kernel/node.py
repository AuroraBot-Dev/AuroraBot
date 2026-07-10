"""The restricted interface Kernel supplies to cognitive nodes."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from src.ai.contracts import ModelRequest, ModelResult
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
    ) -> KernelRecord: ...

    async def request_model_from_node(
        self, parent: KernelRecord, node_id: str, request: ModelRequest
    ) -> ModelResult: ...


@dataclass(frozen=True, slots=True)
class NodeContext:
    """Read-only input and controlled publication surface for one node invocation."""

    record: KernelRecord
    soul_hash: str
    soul_content: str
    configuration_snapshot: dict[str, Any]
    allowed_outputs: frozenset[str]
    allowed_capabilities: frozenset[str]
    _publisher: EventPublisher = field(repr=False)
    _node_id: str = field(repr=False)

    @property
    def amp(self) -> AmpEnvelope:
        return AmpEnvelope.parse(self.record.amp)

    def request_effect(self, capability: str, parameters: dict[str, Any], summary: str) -> KernelRecord:
        if "effect.requested" not in self.allowed_outputs:
            raise NodeContractError(f"{self._node_id} cannot publish effect.requested")
        if capability not in self.allowed_capabilities:
            raise NodeContractError(f"{self._node_id} cannot request {capability}")
        return self._publisher.publish_from_node(
            self.record,
            self._node_id,
            "effect.requested",
            {"capability": capability, "parameters": parameters},
            summary,
        )

    async def request_model(self, request: ModelRequest) -> ModelResult:
        """Request one declared model role through Kernel's auditable capability boundary."""
        if request.role not in self.configuration_snapshot["model_roles"]:
            raise NodeContractError(f"{self._node_id} cannot request model role {request.role}")
        return await self._publisher.request_model_from_node(self.record, self._node_id, request)


class CognitiveNode(Protocol):
    """A self-contained cognitive node with no Platform or workspace access."""

    async def execute(self, context: NodeContext) -> None: ...

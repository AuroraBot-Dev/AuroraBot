"""Narrow ports shared by localhost use cases and external Platform adapters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, Protocol

if TYPE_CHECKING:
    from src.contracts.agent import CapabilityDescriptor, PublicationLease
    from src.localhost.command_types import CommandResult, RuntimeInput

_SUCCESS_WITH_ERROR = "a successful effect outcome cannot contain an error"
_FAILURE_WITHOUT_ERROR = "a failed effect outcome requires an error"
_ACCEPTED_PUBLICATION_INVALID = "accepted Publication requires external_message_id and forbids error"
_UNACCEPTED_PUBLICATION_INVALID = (
    "failed or delivery_unknown Publication requires error and forbids external_message_id"
)
_PUBLICATION_OUTCOME_INVALID = "Publication outcome status and summary must be valid"


class ExternalAmpIngressPort(Protocol):
    """Accept one external AMP fact through the localhost ingress policy."""

    async def submit_amp(self, value: object) -> str: ...


class InteractiveInputPort(Protocol):
    """Route one normalized interactive input through localhost command policy."""

    async def route_input(self, request: RuntimeInput) -> CommandResult: ...


class ConsoleControlPort(InteractiveInputPort, Protocol):
    """Route Console input and request coordinated process shutdown."""

    def request_shutdown(self) -> None: ...


class DashboardControlPort(Protocol):
    """Request coordinated process shutdown from a Dashboard command."""

    def request_shutdown(self) -> None: ...


class DashboardDebugPort(ExternalAmpIngressPort, Protocol):
    """Expose only the localhost diagnostics required by Dashboard debug routes."""

    async def pump(self, max_turns: int | None = None) -> dict[str, Any]: ...

    def status(self) -> dict[str, Any]: ...

    def task(self, task_id: str) -> dict[str, Any] | None: ...

    def agent(self, agent_id: str) -> dict[str, Any] | None: ...

    def brain_context(self) -> dict[str, Any]: ...


@dataclass(frozen=True, slots=True)
class EffectExecutionRequest:
    """Platform-visible effect data without Kernel Activity ownership fields."""

    request_id: str
    session_id: str
    capability: str
    parameters: dict[str, Any]


@dataclass(frozen=True, slots=True)
class EffectOutcome:
    """Structured result of exactly one Platform effect execution."""

    succeeded: bool
    summary: str
    result: dict[str, Any] | None = None
    error: str | None = None

    def __post_init__(self) -> None:
        if self.succeeded and self.error is not None:
            raise ValueError(_SUCCESS_WITH_ERROR)
        if not self.succeeded and (not isinstance(self.error, str) or not self.error):
            raise ValueError(_FAILURE_WITHOUT_ERROR)


class EffectExecutorPort(Protocol):
    """Execute one already-leased effect without accessing Kernel state."""

    async def execute_effect(self, request: EffectExecutionRequest) -> EffectOutcome: ...


@dataclass(frozen=True, slots=True)
class EffectExecutorBinding:
    """Bind one active capability to its unique external executor and AMP source."""

    capability: CapabilityDescriptor
    executor: EffectExecutorPort
    source_app: str
    source_instance: str


PublicationOutcomeStatus = Literal["accepted", "failed", "delivery_unknown"]


@dataclass(frozen=True, slots=True)
class PublicationExecutionRequest:
    """Platform-visible data for one Kernel-authorized Publication."""

    request_id: str
    capability: str
    endpoint_id: str
    operation: Literal["reply", "relay", "proactive_send"]
    text: str
    source_audience_ref: str
    target_audience_ref: str
    root_message_id: str
    route_ref: str | None = None
    destination: str | None = None
    reason: str | None = None
    source_endpoint_id: str | None = None
    source_external_event_id: str | None = None
    hop_count: int = 0
    configuration_hash: str = ""


@dataclass(frozen=True, slots=True)
class PublicationOutcome:
    """The externally observable delivery state of one Publication request."""

    status: PublicationOutcomeStatus
    summary: str
    external_message_id: str | None = None
    error: str | None = None

    def __post_init__(self) -> None:
        if self.status not in {"accepted", "failed", "delivery_unknown"} or not self.summary:
            raise ValueError(_PUBLICATION_OUTCOME_INVALID)
        if self.status == "accepted":
            if not self.external_message_id or self.error is not None:
                raise ValueError(_ACCEPTED_PUBLICATION_INVALID)
        elif not self.error or self.external_message_id is not None:
            raise ValueError(_UNACCEPTED_PUBLICATION_INVALID)


class PublicationExecutorPort(Protocol):
    """Execute one already-authorized Publication without accessing Kernel state."""

    async def execute_publication(self, request: PublicationExecutionRequest) -> PublicationOutcome: ...


class PublicationRecoveryPort(Protocol):
    """Reconcile one Publication left PROCESSING by a prior process."""

    async def recover_publication(self, request: PublicationExecutionRequest) -> PublicationOutcome: ...


class PublicationQueuePort(Protocol):
    """Lease new and interrupted Publication requests from Kernel."""

    async def claim_publication_requests(self) -> tuple[PublicationLease, ...]: ...

    async def publication_recovery_requests(self) -> tuple[PublicationLease, ...]: ...


@dataclass(frozen=True, slots=True)
class PublicationExecutorBinding:
    """Bind one Publication capability to its executor and durable recovery authority."""

    capability: CapabilityDescriptor
    executor: PublicationExecutorPort
    recovery: PublicationRecoveryPort
    source_app: str
    source_instance: str

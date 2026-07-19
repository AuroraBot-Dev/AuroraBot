"""Narrow ports shared by localhost use cases and external Platform adapters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from src.contracts.agent import CapabilityDescriptor
    from src.localhost.command_types import CommandResult, RuntimeInput

_SUCCESS_WITH_ERROR = "a successful effect outcome cannot contain an error"
_FAILURE_WITHOUT_ERROR = "a failed effect outcome requires an error"


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

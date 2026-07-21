"""Narrow ports shared by localhost use cases and external Platform adapters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, Protocol

if TYPE_CHECKING:
    from src.contracts.agent import CapabilityDescriptor, ToolLease
    from src.localhost.command_types import CommandResult, RuntimeInput

_INVALID_OUTCOME = "Tool outcome status and summary must be valid"
_SUCCESS_WITH_ERROR = "a succeeded Tool outcome cannot contain an error"
_FAILURE_WITHOUT_ERROR = "a failed or unknown Tool outcome requires error and forbids result"


class ExternalAmpIngressPort(Protocol):
    async def submit_amp(self, value: object) -> str: ...


class InteractiveInputPort(Protocol):
    async def route_input(self, request: RuntimeInput) -> CommandResult: ...


class ConsoleControlPort(InteractiveInputPort, Protocol):
    def request_shutdown(self) -> None: ...


class DashboardControlPort(Protocol):
    def request_shutdown(self) -> None: ...


class DashboardDebugPort(ExternalAmpIngressPort, Protocol):
    async def pump(self, max_turns: int | None = None) -> dict[str, Any]: ...

    def status(self) -> dict[str, Any]: ...

    def task(self, task_id: str) -> dict[str, Any] | None: ...

    def agent(self, agent_id: str) -> dict[str, Any] | None: ...

    def brain_context(self) -> dict[str, Any]: ...


@dataclass(frozen=True, slots=True)
class ToolExecutionRequest:
    request_id: str
    session_id: str
    capability: str
    parameters: dict[str, Any]


ToolOutcomeStatus = Literal["succeeded", "failed", "unknown"]


@dataclass(frozen=True, slots=True)
class ToolOutcome:
    status: ToolOutcomeStatus
    summary: str
    result: dict[str, Any] | None = None
    error: str | None = None

    def __post_init__(self) -> None:
        if self.status not in {"succeeded", "failed", "unknown"} or not self.summary:
            raise ValueError(_INVALID_OUTCOME)
        if self.status == "succeeded":
            if self.error is not None:
                raise ValueError(_SUCCESS_WITH_ERROR)
        elif not self.error or self.result is not None:
            raise ValueError(_FAILURE_WITHOUT_ERROR)


class ToolExecutor(Protocol):
    async def execute_tool(self, request: ToolExecutionRequest) -> ToolOutcome: ...


class RecoveryBinding(Protocol):
    async def recover_tool(self, request: ToolExecutionRequest) -> ToolOutcome: ...


@dataclass(frozen=True, slots=True)
class ToolExecutorBinding:
    capability: CapabilityDescriptor
    executor: ToolExecutor
    source_app: str
    source_instance: str
    recovery: RecoveryBinding | None = None


class ToolQueuePort(Protocol):
    async def claim_tool_requests(self) -> tuple[ToolLease, ...]: ...

    async def tool_recovery_requests(self) -> tuple[ToolLease, ...]: ...


class ToolCompletionPort(Protocol):
    async def complete_tool(  # noqa: PLR0913 - the narrow port avoids coupling Kernel to localhost DTOs
        self,
        *,
        request_id: str,
        capability: str,
        status: ToolOutcomeStatus,
        summary: str,
        result: dict[str, Any] | None,
        error: str | None,
        source_app: str,
        source_instance: str,
    ) -> None: ...

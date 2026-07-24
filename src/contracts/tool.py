"""工具执行、恢复、绑定与 engine 队列契约。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Literal, Protocol

if TYPE_CHECKING:
    from src.contracts.agent import CapabilityDescriptor, ToolLease


class _Msg(StrEnum):
    INVALID_OUTCOME = "Tool outcome status and summary must be valid"
    SUCCESS_WITH_ERROR = "a succeeded Tool outcome cannot contain an error"
    FAILURE_WITHOUT_ERROR = "a failed or unknown Tool outcome requires error and forbids result"


@dataclass(frozen=True, slots=True)
class ToolExecutionRequest:
    """平台工具执行请求。"""

    request_id: str
    session_id: str
    capability: str
    parameters: dict[str, Any]


ToolOutcomeStatus = Literal["succeeded", "failed", "unknown"]


@dataclass(frozen=True, slots=True)
class ToolOutcome:
    """工具执行的确定性三态结果。"""

    status: ToolOutcomeStatus
    summary: str
    result: dict[str, Any] | None = None
    error: str | None = None

    def __post_init__(self) -> None:
        if self.status not in {"succeeded", "failed", "unknown"} or not self.summary:
            raise ValueError(_Msg.INVALID_OUTCOME)
        if self.status == "succeeded":
            if self.error is not None:
                raise ValueError(_Msg.SUCCESS_WITH_ERROR)
        elif not self.error or self.result is not None:
            raise ValueError(_Msg.FAILURE_WITHOUT_ERROR)


class ToolExecutor(Protocol):
    """执行单个外部工具请求。"""

    async def execute_tool(self, request: ToolExecutionRequest) -> ToolOutcome: ...


class RecoveryBinding(Protocol):
    """恢复单个已进入处理态的工具请求。"""

    async def recover_tool(self, request: ToolExecutionRequest) -> ToolOutcome: ...


@dataclass(frozen=True, slots=True)
class ToolExecutorBinding:
    """能力描述符与具体平台执行器的组合绑定。"""

    capability: CapabilityDescriptor
    executor: ToolExecutor
    source_app: str
    source_instance: str
    recovery: RecoveryBinding | None = None


class ToolQueuePort(Protocol):
    """engine 工具注册表所需的工具租约队列。"""

    async def claim_tool_requests(self) -> tuple[ToolLease, ...]: ...

    async def tool_recovery_requests(self) -> tuple[ToolLease, ...]: ...


class ToolCompletionPort(Protocol):
    """engine 工具注册表写入执行结果的完成端口。"""

    async def complete_tool(
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

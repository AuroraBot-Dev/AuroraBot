"""工具执行、恢复、绑定与 engine 队列契约。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from src.contracts.agent import CapabilityDescriptor

MEMORY_REMEMBER_CAPABILITY = "aurora.memory.remember"
"""主动记忆写入工具 ID：agents 侧能力与 memory 侧执行器的跨层线缆契约。"""


class _Msg(StrEnum):
    INVALID_OUTCOME = "Tool outcome status and summary must be valid"
    SUCCESS_WITH_ERROR = "a succeeded Tool outcome cannot contain an error"
    FAILURE_WITHOUT_ERROR = "a failed or unknown Tool outcome requires error and forbids result"


class ToolOutcomeStatus(StrEnum):
    """工具执行结果的确定性三态。"""

    SUCCEEDED = "succeeded"
    FAILED = "failed"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class ToolExecutionRequest:
    """平台工具执行请求。"""

    request_id: str
    session_id: str
    capability: str
    parameters: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ToolOutcome:
    """工具执行的确定性三态结果。"""

    status: ToolOutcomeStatus
    summary: str
    result: dict[str, Any] | None = None
    error: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, ToolOutcomeStatus) or not self.summary:
            raise ValueError(_Msg.INVALID_OUTCOME)
        if self.status == ToolOutcomeStatus.SUCCEEDED:
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

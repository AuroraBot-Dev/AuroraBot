"""localhost 用例与外部 Platform 适配器共用的窄端口定义。"""

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
    """外部 AMP 入口：接收原始值并解析为 AMP 事件。"""

    async def submit_amp(self, value: object) -> str: ...


class InteractiveInputPort(Protocol):
    """交互式输入入口：接收 RuntimeInput 并路由到命令或对话处理。"""

    async def route_input(self, request: RuntimeInput) -> CommandResult: ...


class ConsoleControlPort(InteractiveInputPort, Protocol):
    """Console 控制端口：组合交互输入与进程级停止请求能力。"""

    def request_shutdown(self) -> None: ...


class DashboardControlPort(Protocol):
    """Dashboard 控制端口：仅暴露进程级停止请求。"""

    def request_shutdown(self) -> None: ...


class DashboardDebugPort(ExternalAmpIngressPort, Protocol):
    """Dashboard 调试端口：在外部 AMP 入口之上扩展泵取、状态查询与详情接口。"""

    async def pump(self, max_turns: int | None = None) -> dict[str, Any]: ...

    def status(self) -> dict[str, Any]: ...

    def task(self, task_id: str) -> dict[str, Any] | None: ...

    def agent(self, agent_id: str) -> dict[str, Any] | None: ...

    def brain_context(self) -> dict[str, Any]: ...


@dataclass(frozen=True, slots=True)
class ToolExecutionRequest:
    """工具执行请求 DTO：包含请求 ID、会话、能力标识与参数。"""

    request_id: str
    session_id: str
    capability: str
    parameters: dict[str, Any]


ToolOutcomeStatus = Literal["succeeded", "failed", "unknown"]


@dataclass(frozen=True, slots=True)
class ToolOutcome:
    """工具执行结果的确定性三态回执。

    成功时不允许携带 error，失败或未知时必须携带 error 且不得有 result。
    """

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
    """工具执行器协议：接收 ToolExecutionRequest 并返回 ToolOutcome。"""

    async def execute_tool(self, request: ToolExecutionRequest) -> ToolOutcome: ...


class RecoveryBinding(Protocol):
    """工具恢复协议：用于恢复未决的工具请求。"""

    async def recover_tool(self, request: ToolExecutionRequest) -> ToolOutcome: ...


@dataclass(frozen=True, slots=True)
class ToolExecutorBinding:
    """将能力描述符与具体执行器、来源信息和可选的恢复绑定在一起。"""

    capability: CapabilityDescriptor
    executor: ToolExecutor
    source_app: str
    source_instance: str
    recovery: RecoveryBinding | None = None


class ToolQueuePort(Protocol):
    """工具队列端口：Kernel 暴露给 localhost 的工具请求认领接口。"""

    async def claim_tool_requests(self) -> tuple[ToolLease, ...]: ...

    async def tool_recovery_requests(self) -> tuple[ToolLease, ...]: ...


class ToolCompletionPort(Protocol):
    """工具完成端口：localhost 通知 Kernel 工具执行结果的窄接口。"""

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

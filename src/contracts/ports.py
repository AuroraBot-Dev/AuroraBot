"""平台到组合层的窄端口契约。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from src.contracts.agent import ToolLease
    from src.contracts.configuration import AuroraConfig
    from src.contracts.event import CommandResult, OutputStreamPage, RuntimeInput
    from src.contracts.tool import ToolOutcomeStatus


class ExternalAmpIngressPort(Protocol):
    """外部平台提交 AMP 的入口。"""

    async def submit_amp(self, value: object) -> str: ...


class InteractiveInputPort(Protocol):
    """交互平台提交命令或会话输入的入口。"""

    async def route_input(self, request: RuntimeInput) -> CommandResult: ...


class ConsoleControlPort(InteractiveInputPort, Protocol):
    """Console 输入与进程停止端口。"""

    def request_shutdown(self) -> None: ...


class DashboardControlPort(Protocol):
    """Dashboard 进程停止端口。"""

    def request_shutdown(self) -> None: ...


class DashboardDebugPort(ExternalAmpIngressPort, Protocol):
    """Dashboard 使用的只读调试与显式推进端口。"""

    async def pump(self, max_turns: int | None = None) -> dict[str, Any]: ...

    def status(self) -> dict[str, Any]: ...

    def task(self, task_id: str) -> dict[str, Any] | None: ...

    def agent(self, agent_id: str) -> dict[str, Any] | None: ...


class RuntimeCommandPort(Protocol):
    """localhost 命令处理器所需的最小运行时端口。"""

    configuration: AuroraConfig

    async def submit_amp(self, value: object) -> str: ...

    async def submit_conversation(self, request: RuntimeInput, text: str) -> str: ...

    async def pump(self, max_turns: int | None = None) -> dict[str, Any]: ...

    def status(self) -> dict[str, Any]: ...

    def task(self, task_id: str) -> dict[str, Any] | None: ...

    def agent(self, agent_id: str) -> dict[str, Any] | None: ...


class RuntimeQueryPort(Protocol):
    """本地交互前端只读查询输出流与运行状态的端口。"""

    def output_stream(self, cursor: int = 0, *, limit: int = 64) -> OutputStreamPage: ...


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

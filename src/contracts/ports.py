"""平台到组合层的窄端口契约。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from src.contracts.event import CommandResult, RuntimeInput


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

    def brain_context(self) -> dict[str, Any]: ...

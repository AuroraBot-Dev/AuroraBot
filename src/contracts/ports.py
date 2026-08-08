"""平台到组合层的窄端口契约（RFC 0218 面板后端）。

端口按域拆分：engine 交互与查询、记忆查询、模型查询、配置查询。
组合根将实现注入 ``PanelRuntime``，ops 面板与操作体系只经这些结构 Protocol 访问运行态。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from src.contracts.configuration import AuroraConfig
    from src.contracts.event import CommandResult, OutputStreamPage, RuntimeInput


class ExternalAmpIngressPort(Protocol):
    """外部提交 AMP 的入口。"""

    async def submit_amp(self, value: object) -> str: ...


class InteractiveInputPort(Protocol):
    """交互前端提交命令或会话输入的入口。"""

    async def route_input(self, request: RuntimeInput) -> CommandResult: ...


class EngineQueryPort(Protocol):
    """engine 热路径的显式操作与只读查询端口（交互 + 运行态观察 + 注入推进）。"""

    async def submit_amp(self, value: object) -> str: ...

    async def submit_conversation(self, request: RuntimeInput, text: str) -> str: ...

    async def pump(self, max_turns: int | None = None) -> dict[str, Any]: ...

    def status(self) -> dict[str, Any]: ...

    def task(self, task_id: str) -> dict[str, Any] | None: ...

    def agent(self, agent_id: str) -> dict[str, Any] | None: ...

    def output_stream(self, cursor: int = 0, *, limit: int = 64) -> OutputStreamPage: ...

    def list_tasks(self, *, status: str | None = None, limit: int = 64) -> list[dict[str, Any]]: ...

    def list_agents(self, *, limit: int = 64) -> list[dict[str, Any]]: ...

    def query_events(
        self,
        *,
        session_id: str | None = None,
        task_id: str | None = None,
        event_type: str | None = None,
        after_id: int = 0,
        limit: int = 64,
    ) -> list[dict[str, Any]]: ...

    def session_export(self, session_id: str) -> dict[str, Any] | None: ...


class MemoryQueryPort(Protocol):
    """记忆引擎（RFC 0216）的只读查询端口。"""

    def history(self, *, scope: str | None = None, limit: int = 32) -> list[dict[str, Any]]: ...

    def search(self, query: str, *, scope: str | None = None, limit: int = 8) -> list[dict[str, Any]]: ...

    def status(self) -> dict[str, Any]: ...


class AiQueryPort(Protocol):
    """模型网关（RFC 0215）的只读查询端口。"""

    def cost(self) -> dict[str, Any]: ...

    def models(self) -> list[dict[str, Any]]: ...

    def roles(self) -> list[dict[str, Any]]: ...


class ConfigQueryPort(Protocol):
    """启动配置快照（RFC 0206）与提示词的只读查询端口。"""

    def snapshot(self) -> dict[str, Any]: ...

    def prompt_for(self, role: str) -> dict[str, Any] | None: ...


@dataclass(frozen=True, slots=True)
class PanelRuntime:
    """操作体系可见的全部后端端口聚合（RFC 0218 §2/§5）。"""

    engine: EngineQueryPort
    memory: MemoryQueryPort
    ai: AiQueryPort
    config: ConfigQueryPort


class ConsoleControlPort(InteractiveInputPort, Protocol):
    """Console 输入与进程停止端口。"""

    def request_shutdown(self) -> None: ...


class RuntimeQueryPort(Protocol):
    """本地交互前端只读查询输出流的端口。"""

    def output_stream(self, cursor: int = 0, *, limit: int = 64) -> OutputStreamPage: ...

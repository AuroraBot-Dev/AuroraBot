"""跨包能力契约：模块之间只经这些 Protocol 互联。

具体实现由各 ``src/<pkg>`` 提供；消费方只依赖本模块，不 import 兄弟包的实现。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    import asyncio
    from collections.abc import Callable, Mapping

    from src.contracts.agent import AgentDefinition, AgentTree, TreeLauncher
    from src.contracts.console import TerminalDispatcher
    from src.contracts.model import ChatMessage
    from src.contracts.tool import ToolCall, ToolDefinition, ToolResult, ToolScopes
    from src.contracts.world import MemorySnapshot


class PromptCatalog(Protocol):
    """四角色提示词目录。"""

    @property
    def system(self) -> tuple[str, ...]: ...

    @property
    def agent_prompts(self) -> Mapping[str, str]: ...


class PromptAssembler(Protocol):
    """把节点组装为模型上下文的确定性组装器。"""

    @property
    def catalog(self) -> PromptCatalog: ...

    def assemble(
        self,
        tree: AgentTree,
        node_id: str,
        *,
        memory: MemorySnapshot | None = None,
    ) -> tuple[ChatMessage, ...]: ...


class AgentCatalog(Protocol):
    """definition ID → AgentDefinition 的只读目录。"""

    @property
    def definitions(self) -> tuple[AgentDefinition, ...]: ...

    @property
    def ids(self) -> frozenset[str]: ...

    def get(self, definition_id: str) -> AgentDefinition: ...


class ToolRegistry(Protocol):
    """一次组合内不可变的工具目录与唯一执行路由。"""

    @property
    def names(self) -> frozenset[str]: ...

    @property
    def definitions(self) -> tuple[ToolDefinition, ...]: ...

    def definitions_for(self, visible: frozenset[str]) -> tuple[ToolDefinition, ...]: ...

    def scopes_for(self, call: ToolCall) -> ToolScopes: ...

    async def execute(self, call: ToolCall) -> ToolResult: ...


class AgentTreeRunner(Protocol):
    """按给定树执行一次认知运行的引擎端口。"""

    @property
    def tool_definitions(self) -> tuple[ToolDefinition, ...]: ...

    async def run(self, tree: AgentTree, observer: Callable[[AgentTree], None] | None = None) -> AgentTree: ...


class TerminalConsole(Protocol):
    """本地终端前端。"""

    async def run(
        self,
        dispatcher: TerminalDispatcher,
        *,
        stop_event: asyncio.Event | None = None,
        readline: Callable[[str], str] | None = None,
        output: Callable[[str], None] = print,
    ) -> None: ...


class Cadence(Protocol):
    """世界提交驱动的主动节律。"""

    @property
    def enabled(self) -> bool: ...

    async def initialize(self) -> None: ...

    async def run(self, stop: asyncio.Event) -> None: ...

    def bind_launcher(self, launcher: TreeLauncher) -> None: ...


class McpRuntime(Protocol):
    """MCP 客户端运行期目录与生命周期。"""

    @property
    def tools(self) -> tuple[object, ...]: ...

    async def activate(self) -> None: ...

    async def close(self) -> None: ...

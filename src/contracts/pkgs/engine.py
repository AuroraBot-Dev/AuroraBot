"""``engine`` 暴露的全局端口：AgentTree 运行器契约。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Callable

    from src.contracts.agent import AgentTree
    from src.contracts.tool import ToolDefinition


class AgentTreeRunner(Protocol):
    """按给定树执行一次认知运行的引擎端口。"""

    @property
    def tool_definitions(self) -> tuple[ToolDefinition, ...]: ...

    async def run(self, tree: AgentTree, observer: Callable[[AgentTree], None] | None = None) -> AgentTree: ...

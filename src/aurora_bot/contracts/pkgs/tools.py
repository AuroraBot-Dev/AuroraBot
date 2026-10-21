"""``tools`` 暴露的全局端口：工具目录与唯一执行路由契约。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from aurora_bot.contracts.tool import ToolCall, ToolDefinition, ToolResult
    from aurora_bot.contracts.world import ToolScopes


class ToolRegistry(Protocol):
    """一次组合内不可变的工具目录与唯一执行路由。"""

    @property
    def names(self) -> frozenset[str]: ...

    @property
    def definitions(self) -> tuple[ToolDefinition, ...]: ...

    def definitions_for(self, visible: frozenset[str]) -> tuple[ToolDefinition, ...]: ...

    def scopes_for(self, call: ToolCall) -> ToolScopes: ...

    async def execute(self, call: ToolCall) -> ToolResult: ...

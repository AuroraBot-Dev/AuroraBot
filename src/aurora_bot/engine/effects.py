"""认知循环提交世界效果的抽象端口，以及无世界线时的空实现。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from aurora_bot.contracts import WorldFrontier

if TYPE_CHECKING:
    from collections.abc import Mapping

    from aurora_bot.contracts import (
        AgentNode,
        AgentTree,
        ChatMessage,
        ModelRequest,
        ToolCall,
        ToolOutput,
        ToolScopes,
        WorldDeltaPage,
    )
    from aurora_bot.contracts.memory import MemoryExposure


class EngineEffectSink(Protocol):
    """引擎单步认知产生的世界效果；实现负责持久化并回传需要推进的观察前沿。"""

    async def tree_started(self, tree: AgentTree) -> None: ...

    async def tree_failed(self, tree: AgentTree, error: str, data: Mapping[str, object]) -> None: ...

    async def model_requested(
        self, tree: AgentTree, node: AgentNode, request: ModelRequest, *, memory: MemoryExposure | None = None
    ) -> None: ...

    async def model_failed(self, tree: AgentTree, node: AgentNode, error: str) -> None: ...

    async def model_role_invalid(self, tree: AgentTree, node: AgentNode, role: str) -> None: ...

    async def model_completed(self, tree: AgentTree, node: AgentNode, response: ChatMessage) -> WorldFrontier: ...

    async def scope_rejected(
        self,
        tree: AgentTree,
        node_id: str,
        calls: tuple[ToolCall, ...],
        error: Exception,
    ) -> None: ...

    async def delta_delivered(
        self,
        tree: AgentTree,
        node_id: str,
        delta: WorldDeltaPage,
        *,
        commit_id: str,
        call_ids: tuple[str, ...] = (),
    ) -> None: ...

    async def tool_requests(
        self,
        tree: AgentTree,
        node_id: str,
        calls: tuple[ToolCall, ...],
        scopes: Mapping[str, ToolScopes],
    ) -> WorldFrontier: ...

    async def tool_output(
        self,
        tree: AgentTree,
        node_id: str,
        call: ToolCall,
        output: ToolOutput,
        scopes: ToolScopes,
    ) -> WorldFrontier: ...

    async def node_spawned(self, tree: AgentTree, child: AgentNode) -> None: ...

    async def root_completion(self, tree: AgentTree, node_id: str, result: str) -> WorldFrontier: ...

    async def delegation_completion(
        self,
        tree: AgentTree,
        child: AgentNode,
        content: str,
        *,
        is_error: bool,
    ) -> WorldFrontier: ...


class NullEffectSink:
    """无世界线时的空实现：不提交任何事件，也不推进任何前沿。"""

    async def tree_started(self, tree: AgentTree) -> None:
        pass

    async def tree_failed(self, tree: AgentTree, error: str, data: Mapping[str, object]) -> None:
        pass

    async def model_requested(
        self, tree: AgentTree, node: AgentNode, request: ModelRequest, *, memory: MemoryExposure | None = None
    ) -> None:
        """没有世界线时不保存上下文来源。"""

    async def model_failed(self, tree: AgentTree, node: AgentNode, error: str) -> None:
        pass

    async def model_role_invalid(self, tree: AgentTree, node: AgentNode, role: str) -> None:
        pass

    async def model_completed(self, tree: AgentTree, node: AgentNode, response: ChatMessage) -> WorldFrontier:
        return WorldFrontier()

    async def scope_rejected(
        self,
        tree: AgentTree,
        node_id: str,
        calls: tuple[ToolCall, ...],
        error: Exception,
    ) -> None:
        pass

    async def delta_delivered(
        self,
        tree: AgentTree,
        node_id: str,
        delta: WorldDeltaPage,
        *,
        commit_id: str,
        call_ids: tuple[str, ...] = (),
    ) -> None:
        pass

    async def tool_requests(
        self,
        tree: AgentTree,
        node_id: str,
        calls: tuple[ToolCall, ...],
        scopes: Mapping[str, ToolScopes],
    ) -> WorldFrontier:
        return WorldFrontier()

    async def tool_output(
        self,
        tree: AgentTree,
        node_id: str,
        call: ToolCall,
        output: ToolOutput,
        scopes: ToolScopes,
    ) -> WorldFrontier:
        return WorldFrontier()

    async def node_spawned(self, tree: AgentTree, child: AgentNode) -> None:
        pass

    async def root_completion(self, tree: AgentTree, node_id: str, result: str) -> WorldFrontier:
        return WorldFrontier()

    async def delegation_completion(
        self,
        tree: AgentTree,
        child: AgentNode,
        content: str,
        *,
        is_error: bool,
    ) -> WorldFrontier:
        return WorldFrontier()

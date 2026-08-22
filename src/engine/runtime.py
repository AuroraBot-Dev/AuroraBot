"""AgentTree 的确定性单循环运行时。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.contracts import (
    AgentTree,
    ChatMessage,
    DelegationRequest,
    Model,
    ModelRequest,
    ToolCall,
    ToolOutput,
    TreeStatus,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from src.agents import AgentCatalog
    from src.prompt import PromptAssembler
    from src.tools import ToolRegistry


class AgentTreeRunner:
    """按深度优先顺序运行一棵 AgentTree，直到 root 终止。"""

    def __init__(
        self,
        model: Model,
        assembler: PromptAssembler,
        agents: AgentCatalog,
        tools: ToolRegistry,
        *,
        max_depth: int = 4,
        max_nodes: int = 32,
        max_steps: int = 256,
    ) -> None:
        if min(max_depth, max_nodes, max_steps) <= 0:
            raise ValueError("runner limits must be positive")
        self._model = model
        self._assembler = assembler
        self._agents = agents
        self._tools = tools
        self._max_depth = max_depth
        self._max_nodes = max_nodes
        self._max_steps = max_steps

    async def run(self, tree: AgentTree, observer: Callable[[AgentTree], None] | None = None) -> AgentTree:
        self._validate_definitions(tree)
        current = self._publish(tree, observer)
        for _ in range(self._max_steps):
            if current.status != TreeStatus.RUNNING:
                return current
            node = current.ready_node()
            if node is None:
                raise RuntimeError("running AgentTree has no ready node")
            if node.pending_calls:
                current = self._publish(
                    await self._execute_call(current, node.node_id, node.pending_calls[0]),
                    observer,
                )
                continue
            try:
                definitions = self._tools.definitions_for(node.tools)
                response = await self._model.complete(
                    ModelRequest(node.model, self._assembler.assemble(current, node.node_id), definitions)
                )
            except Exception as error:
                current = self._publish(current.fail(node.node_id, f"model failed: {error}"), observer)
                continue
            if response.role != "assistant":
                current = self._publish(current.fail(node.node_id, "model must return an assistant message"), observer)
                continue
            current = self._publish(current.append(node.node_id, response), observer)
            if not response.tool_calls:
                current = self._publish(current.complete(node.node_id, response.content), observer)
        raise RuntimeError(f"AgentTree exceeded step limit {self._max_steps}")

    @staticmethod
    def _publish(tree: AgentTree, observer: Callable[[AgentTree], None] | None) -> AgentTree:
        if observer is not None:
            observer(tree)
        return tree

    def _validate_definitions(self, tree: AgentTree) -> None:
        for node in tree.nodes:
            definition = self._agents.get(node.definition_id)
            if (node.prompt_id, node.model, node.tools) != (
                definition.prompt_id,
                definition.model,
                definition.tools,
            ):
                raise ValueError(f"AgentNode 与预定义原型不一致：{node.node_id}")

    async def _execute_call(self, tree: AgentTree, node_id: str, call: ToolCall) -> AgentTree:
        if call.name not in tree.node(node_id).tools:
            return tree.append(
                node_id,
                ChatMessage.tool(call.call_id, f"当前 Agent 不可见此工具：{call.name}", is_error=True),
            )
        result = await self._tools.execute(call)
        if isinstance(result, ToolOutput):
            return tree.append(node_id, ChatMessage.tool(call.call_id, result.content, is_error=result.is_error))
        return self._apply_delegation(tree, node_id, call, result)

    def _apply_delegation(
        self,
        tree: AgentTree,
        node_id: str,
        call: ToolCall,
        request: DelegationRequest,
    ) -> AgentTree:
        parent = self._agents.get(tree.node(node_id).definition_id)
        if request.agent not in parent.children:
            return tree.append(
                node_id,
                ChatMessage.tool(call.call_id, f"当前 Agent 不允许委派给：{request.agent}", is_error=True),
            )
        if len(tree.nodes) >= self._max_nodes:
            return tree.append(node_id, ChatMessage.tool(call.call_id, "AgentTree 已达到节点数上限", is_error=True))
        if tree.depth(node_id) >= self._max_depth:
            return tree.append(node_id, ChatMessage.tool(call.call_id, "AgentTree 已达到深度上限", is_error=True))
        return tree.spawn(node_id, call, self._agents.get(request.agent), request.instruction)

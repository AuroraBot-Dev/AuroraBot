"""AgentTree 的确定性单循环运行时。"""

from __future__ import annotations

from types import MappingProxyType
from typing import TYPE_CHECKING

from src.contracts import (
    AgentTree,
    ChatMessage,
    Model,
    ModelRequest,
    Tool,
    ToolCall,
    ToolDefinition,
    ToolOutput,
    TreeStatus,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from src.prompt import PromptAssembler

DELEGATE_TOOL = "delegate"
DELEGATE_DEFINITION = ToolDefinition(
    DELEGATE_TOOL,
    "Create a child Agent for one focused assignment.",
    {
        "type": "object",
        "properties": {
            "profile": {"type": "string"},
            "model": {"type": "string"},
            "tools": {"type": "array", "items": {"type": "string"}, "uniqueItems": True},
            "instruction": {"type": "string"},
        },
        "required": ["profile", "model", "instruction"],
        "additionalProperties": False,
    },
)


class AgentTreeRunner:
    """按深度优先顺序运行一棵 AgentTree，直到 root 终止。"""

    def __init__(
        self,
        model: Model,
        assembler: PromptAssembler,
        tools: Iterable[Tool] = (),
        *,
        max_depth: int = 4,
        max_nodes: int = 32,
        max_steps: int = 256,
    ) -> None:
        if min(max_depth, max_nodes, max_steps) <= 0:
            raise ValueError("runner limits must be positive")
        registered = tuple(tools)
        by_name = {tool.definition.name: tool for tool in registered}
        if len(by_name) != len(registered):
            raise ValueError("Tool names must be unique")
        if DELEGATE_TOOL in by_name:
            raise ValueError("delegate is reserved by AgentTreeRunner")
        self._model = model
        self._assembler = assembler
        self._tools = MappingProxyType(by_name)
        self._definitions = (DELEGATE_DEFINITION, *(tool.definition for tool in by_name.values()))
        self._max_depth = max_depth
        self._max_nodes = max_nodes
        self._max_steps = max_steps

    async def run(self, tree: AgentTree, observer: Callable[[AgentTree], None] | None = None) -> AgentTree:
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
                definitions = tuple(definition for definition in self._definitions if definition.name in node.tools)
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

    async def _execute_call(self, tree: AgentTree, node_id: str, call: ToolCall) -> AgentTree:
        if call.name not in tree.node(node_id).tools:
            return tree.append(
                node_id,
                ChatMessage.tool(call.call_id, f"tool is not visible to this Agent: {call.name}", is_error=True),
            )
        if call.name == DELEGATE_TOOL:
            return self._delegate(tree, node_id, call)
        tool = self._tools.get(call.name)
        if tool is None:
            return tree.append(node_id, ChatMessage.tool(call.call_id, f"unknown tool: {call.name}", is_error=True))
        try:
            output = await tool.execute(call)
        except Exception as error:
            output = ToolOutput(f"tool failed: {error}", is_error=True)
        return tree.append(node_id, ChatMessage.tool(call.call_id, output.content, is_error=output.is_error))

    def _delegate(self, tree: AgentTree, node_id: str, call: ToolCall) -> AgentTree:
        profile = call.arguments.get("profile")
        model = call.arguments.get("model")
        tool_names = call.arguments.get("tools", [])
        instruction = call.arguments.get("instruction")
        valid_tools = isinstance(tool_names, list) and all(isinstance(name, str) and name for name in tool_names)
        if (
            not isinstance(profile, str)
            or not profile.strip()
            or not isinstance(model, str)
            or not model.strip()
            or not valid_tools
            or not isinstance(instruction, str)
            or not instruction.strip()
        ):
            return tree.append(
                node_id,
                ChatMessage.tool(
                    call.call_id,
                    "delegate requires non-empty profile, model and instruction plus a string tools array",
                    is_error=True,
                ),
            )
        requested_tools = frozenset(tool_names)
        available_tools = frozenset(definition.name for definition in self._definitions)
        unknown_tools = requested_tools - available_tools
        if unknown_tools:
            names = ", ".join(sorted(unknown_tools))
            return tree.append(node_id, ChatMessage.tool(call.call_id, f"unknown child tools: {names}", is_error=True))
        if len(tree.nodes) >= self._max_nodes:
            return tree.append(node_id, ChatMessage.tool(call.call_id, "AgentTree node limit reached", is_error=True))
        if tree.depth(node_id) >= self._max_depth:
            return tree.append(node_id, ChatMessage.tool(call.call_id, "AgentTree depth limit reached", is_error=True))
        return tree.spawn(node_id, call, profile.strip(), model.strip(), requested_tools, instruction.strip())

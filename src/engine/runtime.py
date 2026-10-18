"""AgentTree 的确定性单循环运行时。"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from src.contracts import (
    AgentNode,
    AgentTree,
    ChatMessage,
    DelegationRequest,
    ModelRequest,
    ToolCall,
    ToolOutput,
    ToolScopes,
    ToolStatus,
    TreeStatus,
)
from src.contracts.memory import MemoryRequest
from src.contracts.model import ContextBudgetError, ToolContext
from src.engine.effects import NullEffectSink
from src.engine.world_effects import EngineWorldEffects, render_delta
from src.utils import get_logger

_logger = get_logger(__name__)

if TYPE_CHECKING:
    from collections.abc import Callable

    from src.contracts import ToolDefinition
    from src.contracts.pkgs.agents import AgentCatalog
    from src.contracts.pkgs.ai import Model
    from src.contracts.pkgs.memory import MemoryReader
    from src.contracts.pkgs.prompt import PromptAssembler
    from src.contracts.pkgs.tools import ToolRegistry
    from src.contracts.pkgs.world import WorldJournal
    from src.engine.effects import EngineEffectSink


class AgentTreeRunner:
    """按深度优先顺序运行一棵 AgentTree，直到 root 终止。"""

    def __init__(
        self,
        model: Model,
        assembler: PromptAssembler,
        agents: AgentCatalog,
        tools: ToolRegistry,
        *,
        world: WorldJournal | None = None,
        memory: MemoryReader | None = None,
        bot_id: str = "aurora:bot/default",
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
        self._world = world
        self._effects: EngineEffectSink = (
            EngineWorldEffects(world, bot_id=bot_id) if world is not None else NullEffectSink()
        )
        self._memory = memory
        self._bot_id = bot_id
        self._max_depth = max_depth
        self._max_nodes = max_nodes
        self._max_steps = max_steps

    @property
    def tool_definitions(self) -> tuple[ToolDefinition, ...]:
        """暴露当前不可变工具目录供只读观察；核心循环不依赖此属性。"""
        return self._tools.definitions

    async def run(self, tree: AgentTree, observer: Callable[[AgentTree], None] | None = None) -> AgentTree:
        _logger.info("AgentTree 开始 tree_id={} root_id={}", tree.tree_id, tree.root_id)
        self._validate_definitions(tree)
        if self._world is not None:
            await self._world.initialize()
        await self._effects.tree_started(tree)
        current = self._publish(tree, observer)
        for _ in range(self._max_steps):
            if current.status != TreeStatus.RUNNING:
                _logger.info(
                    "AgentTree 结束 tree_id={} status={} node_count={}",
                    current.tree_id,
                    current.status.value,
                    len(current.nodes),
                )
                return current
            node = current.ready_node()
            if node is None:
                raise RuntimeError("running AgentTree has no ready node")
            if node.pending_calls:
                current = self._publish(
                    await self._execute_pending(current, node.node_id, node.pending_calls),
                    observer,
                )
                continue
            current = await self._model_step(current, node, observer)
        await self._effects.tree_failed(
            current,
            "step limit exceeded",
            {"tree_id": current.tree_id, "max_steps": self._max_steps},
        )
        _logger.error("AgentTree 超出步数限制 tree_id={} max_steps={}", current.tree_id, self._max_steps)
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

    async def _model_step(
        self,
        tree: AgentTree,
        node: AgentNode,
        observer: Callable[[AgentTree], None] | None,
    ) -> AgentTree:
        step_index = sum(message.role == "assistant" for message in node.messages)
        try:
            memory = (
                await self._memory.recall(
                    MemoryRequest(
                        query="\n".join(message.content for message in (node.messages[:1] + node.messages[-1:])),
                        focus_goal_ids=node.focus_goal_ids,
                        scopes=node.memory_scopes,
                    )
                )
                if self._memory is not None
                else None
            )
            assembled = self._assembler.assemble(tree, node.node_id, memory=memory)
            request = ModelRequest(
                node.model,
                assembled.messages,
                self._tools.definitions_for(node.tools),
            )
        except ContextBudgetError as error:
            return self._publish(await self._fail_node(tree, node.node_id, str(error)), observer)
        _logger.debug(
            "模型步骤开始 tree_id={} node_id={} model={} step={}",
            tree.tree_id,
            node.node_id,
            node.model,
            step_index,
        )
        await self._effects.model_requested(tree, node, request, memory=assembled.memory)
        try:
            response = await self._model.complete(request)
        except Exception as error:
            _logger.error(
                "模型步骤失败 tree_id={} node_id={} model={} error_type={}",
                tree.tree_id,
                node.node_id,
                node.model,
                type(error).__name__,
            )
            await self._effects.model_failed(tree, node, str(error))
            return await self._fail_node(tree, node.node_id, f"model failed: {error}")
        if response.role != "assistant":
            reason = "model must return an assistant message"
            _logger.error("模型响应角色无效 tree_id={} node_id={} role={}", tree.tree_id, node.node_id, response.role)
            await self._effects.model_role_invalid(tree, node, response.role)
            return await self._fail_node(tree, node.node_id, reason)
        frontier = await self._effects.model_completed(tree, node, response)
        tree = tree.append(node.node_id, response).advance_frontier(node.node_id, frontier)
        _logger.debug(
            "模型步骤完成 tree_id={} node_id={} tool_call_count={}",
            tree.tree_id,
            node.node_id,
            len(response.tool_calls),
        )
        tree = self._publish(tree, observer)
        if response.tool_calls:
            return tree
        return self._publish(await self._complete_node(tree, node.node_id, response.content), observer)

    async def _execute_pending(self, tree: AgentTree, node_id: str, calls: tuple[ToolCall, ...]) -> AgentTree:
        """检查并封口一个 assistant Tool batch，随后只执行其中的下一个调用。"""
        node = tree.node(node_id)
        if self._world is not None and not set(call.call_id for call in calls) <= node.sealed_call_ids:
            try:
                scopes = self._resolve_scopes(tree, node_id, calls)
            except Exception as error:
                return await self._reject_scope_batch(tree, node_id, calls, error)
            if not node.reviewed_world_update:
                tool_scopes = {scope for item in scopes.values() for scope in item.observe}
                tree = tree.watch_scopes(node_id, frozenset(tool_scopes))
                observe_scopes = node.observation_scopes | tool_scopes
                delta = await self._world.delta(node.observed_frontier, observe_scopes)
                if delta.commits:
                    await self._effects.delta_delivered(
                        tree,
                        node_id,
                        delta,
                        commit_id=f"{tree.tree_id}:{node_id}:{calls[0].call_id}:world-delta",
                        call_ids=tuple(call.call_id for call in calls),
                    )
                    return tree.defer_tools_for_world(
                        node_id,
                        tuple(call.call_id for call in calls),
                        render_delta(delta),
                        delta.end,
                        reviewed=not delta.has_more,
                    )
            requested = await self._effects.tool_requests(tree, node_id, calls, scopes)
            tree = tree.advance_frontier(node_id, requested).seal_calls(
                node_id,
                tuple(call.call_id for call in calls),
                scopes,
            )
        return await self._execute_call(tree, node_id, calls[0])

    async def _reject_scope_batch(
        self,
        tree: AgentTree,
        node_id: str,
        calls: tuple[ToolCall, ...],
        error: Exception,
    ) -> AgentTree:
        await self._effects.scope_rejected(tree, node_id, calls, error)
        rejected = tree
        for call in calls:
            rejected = rejected.append(
                node_id,
                ChatMessage.tool(call.call_id, f"工具 scope 解析失败：{error}", is_error=True),
            )
        return rejected

    def _resolve_scopes(self, tree: AgentTree, node_id: str, calls: tuple[ToolCall, ...]) -> dict[str, ToolScopes]:
        scopes: dict[str, ToolScopes] = {}
        for call in calls:
            resolved = self._tools.scopes_for(self._contextual_call(tree, node_id, call))
            if not isinstance(resolved, ToolScopes):
                raise TypeError(f"工具 scope resolver 返回无效结果：{call.name}")
            scopes[call.call_id] = resolved
        return scopes

    async def _execute_call(self, tree: AgentTree, node_id: str, call: ToolCall) -> AgentTree:
        if call.name not in tree.node(node_id).tools:
            return await self._append_tool_output(
                tree,
                node_id,
                call,
                ToolOutput(f"当前 Agent 不可见此工具：{call.name}", status=ToolStatus.FAILED),
            )
        result = await self._tools.execute(self._contextual_call(tree, node_id, call))
        if isinstance(result, ToolOutput):
            return await self._append_tool_output(tree, node_id, call, result)
        delegated, rejection = await self._apply_delegation(tree, node_id, call, result)
        if rejection is not None:
            return await self._append_tool_output(tree, node_id, call, rejection)
        return delegated

    def _contextual_call(self, tree: AgentTree, node_id: str, call: ToolCall) -> ToolCall:
        """用实际运行归属覆盖调用上下文，保留模型原始调用身份。"""
        cause = f"{tree.tree_id}:{node_id}:{call.call_id}:requested" if self._world is not None else None
        return replace(call, context=ToolContext(self._bot_id, tree.tree_id, node_id, cause))

    async def _apply_delegation(
        self,
        tree: AgentTree,
        node_id: str,
        call: ToolCall,
        request: DelegationRequest,
    ) -> tuple[AgentTree, ToolOutput | None]:
        parent = self._agents.get(tree.node(node_id).definition_id)
        if request.agent not in parent.children:
            return tree, ToolOutput(f"当前 Agent 不允许委派给：{request.agent}", status=ToolStatus.FAILED)
        if len(tree.nodes) >= self._max_nodes:
            return tree, ToolOutput("AgentTree 已达到节点数上限", status=ToolStatus.FAILED)
        if tree.depth(node_id) >= self._max_depth:
            return tree, ToolOutput("AgentTree 已达到深度上限", status=ToolStatus.FAILED)
        spawned = tree.spawn(node_id, call, self._agents.get(request.agent), request.instruction)
        _logger.info(
            "AgentNode 已委派 tree_id={} parent_id={} child_agent={}",
            tree.tree_id,
            node_id,
            request.agent,
        )
        child = spawned.node(f"{tree.tree_id}:{len(tree.nodes)}")
        await self._effects.node_spawned(tree, child)
        return spawned, None

    async def _append_tool_output(
        self,
        tree: AgentTree,
        node_id: str,
        call: ToolCall,
        output: ToolOutput,
    ) -> AgentTree:
        node = tree.node(node_id)
        scopes = node.sealed_call_scopes.get(call.call_id, ToolScopes())
        frontier = await self._effects.tool_output(tree, node_id, call, output, scopes)
        tree = tree.advance_frontier(node_id, frontier)
        return tree.append(node_id, ChatMessage.tool(call.call_id, output.content, is_error=output.is_error))

    async def _complete_node(self, tree: AgentTree, node_id: str, result: str) -> AgentTree:
        node = tree.node(node_id)
        if self._world is not None and not node.reviewed_world_update:
            delta = await self._world.delta(node.observed_frontier, node.observation_scopes)
            if delta.commits:
                await self._effects.delta_delivered(
                    tree,
                    node_id,
                    delta,
                    commit_id=f"{tree.tree_id}:{node_id}:complete-delta:{len(node.messages)}",
                )
                return tree.observe(
                    node_id,
                    ChatMessage.message(render_delta(delta)),
                    delta.end,
                    reviewed=not delta.has_more,
                )
        if node.parent_id is not None:
            completed = tree.complete(node_id, result)
            return await self._record_delegation_completion(completed, node, result, is_error=False)
        frontier = await self._effects.root_completion(tree, node_id, result)
        tree = tree.advance_frontier(node_id, frontier)
        return tree.complete(node_id, result)

    async def _fail_node(self, tree: AgentTree, node_id: str, error: str) -> AgentTree:
        node = tree.node(node_id)
        if node.parent_id is None:
            await self._effects.tree_failed(
                tree,
                error,
                {"tree_id": tree.tree_id, "node_id": node_id},
            )
            return tree.fail(node_id, error)
        failed = tree.fail(node_id, error)
        return await self._record_delegation_completion(failed, node, error, is_error=True)

    async def _record_delegation_completion(
        self,
        tree: AgentTree,
        child: AgentNode,
        content: str,
        *,
        is_error: bool,
    ) -> AgentTree:
        assert child.parent_id is not None
        frontier = await self._effects.delegation_completion(tree, child, content, is_error=is_error)
        return tree.advance_frontier(child.parent_id, frontier)

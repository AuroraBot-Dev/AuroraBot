"""AgentTree 的确定性单循环运行时。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.contracts import (
    MODEL_COMPLETED,
    MODEL_FAILED,
    MODEL_REQUESTED,
    TOOL_FAILED,
    AgentNode,
    AgentTree,
    ChatMessage,
    DelegationRequest,
    MemoryReader,
    Model,
    ModelRequest,
    ToolCall,
    ToolOutput,
    ToolScopes,
    ToolStatus,
    TreeStatus,
    WorldCommit,
    WorldFrontier,
    WorldJournal,
    tree_scope,
)
from src.engine.world_effects import EngineWorldEffects, render_delta
from src.utils import get_logger

_logger = get_logger(__name__)

if TYPE_CHECKING:
    from collections.abc import Callable

    from src.agents import AgentCatalog
    from src.contracts import ToolDefinition
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
        world: WorldJournal | None = None,
        memory: MemoryReader | None = None,
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
        self._world_effects = EngineWorldEffects(world) if world is not None else None
        self._memory = memory
        self._max_depth = max_depth
        self._max_nodes = max_nodes
        self._max_steps = max_steps

    @property
    def tool_definitions(self) -> tuple[ToolDefinition, ...]:
        """暴露当前不可变工具目录给 ops 监测；核心循环不依赖此属性。"""
        return self._tools.definitions

    async def run(self, tree: AgentTree, observer: Callable[[AgentTree], None] | None = None) -> AgentTree:
        _logger.info("AgentTree 开始 tree_id=%s root_id=%s", tree.tree_id, tree.root_id)
        self._validate_definitions(tree)
        if self._world is not None:
            await self._world.initialize()
            assert self._world_effects is not None
            await self._world_effects.record_tree_started(tree)
        current = self._publish(tree, observer)
        for _ in range(self._max_steps):
            if current.status != TreeStatus.RUNNING:
                _logger.info(
                    "AgentTree 结束 tree_id=%s status=%s node_count=%d",
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
        if self._world is not None:
            assert self._world_effects is not None
            await self._world_effects.record_tree_failed(
                current,
                "step limit exceeded",
                {"tree_id": current.tree_id, "max_steps": self._max_steps},
            )
        _logger.error("AgentTree 超出步数限制 tree_id=%s max_steps=%d", current.tree_id, self._max_steps)
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
        prefix = f"{tree.tree_id}:{node.node_id}:model:{step_index}"
        memory = await self._memory.recall() if self._memory is not None else None
        request = ModelRequest(
            node.model,
            self._assembler.assemble(tree, node.node_id, memory=memory),
            self._tools.definitions_for(node.tools),
        )
        _logger.debug(
            "模型步骤开始 tree_id=%s node_id=%s model=%s step=%d",
            tree.tree_id,
            node.node_id,
            node.model,
            step_index,
        )
        if self._world is not None:
            assert self._world_effects is not None
            await self._world_effects.append_commit(
                commit_id=f"{prefix}:requested",
                kind=MODEL_REQUESTED,
                summary=f"请求模型：{node.model}",
                scopes=frozenset({tree_scope(tree.tree_id)}),
                based_on=node.observed_frontier,
                data={
                    "tree_id": tree.tree_id,
                    "node_id": node.node_id,
                    "model": node.model,
                    "message_count": len(request.messages),
                    "tool_count": len(request.tools),
                },
            )
        try:
            response = await self._model.complete(request)
        except Exception as error:
            _logger.error(
                "模型步骤失败 tree_id=%s node_id=%s model=%s error_type=%s",
                tree.tree_id,
                node.node_id,
                node.model,
                type(error).__name__,
            )
            if self._world is not None:
                assert self._world_effects is not None
                await self._world_effects.append_commit(
                    commit_id=f"{prefix}:failed",
                    kind=MODEL_FAILED,
                    summary=f"模型失败：{error}",
                    scopes=frozenset({tree_scope(tree.tree_id)}),
                    based_on=node.observed_frontier,
                    data={
                        "tree_id": tree.tree_id,
                        "node_id": node.node_id,
                        "model": node.model,
                        "error": str(error),
                    },
                )
            return await self._fail_node(tree, node.node_id, f"model failed: {error}")
        if response.role != "assistant":
            reason = "model must return an assistant message"
            _logger.error("模型响应角色无效 tree_id=%s node_id=%s role=%s", tree.tree_id, node.node_id, response.role)
            if self._world is not None:
                assert self._world_effects is not None
                await self._world_effects.append_commit(
                    commit_id=f"{prefix}:failed",
                    kind=MODEL_FAILED,
                    summary=f"模型失败：{reason}",
                    scopes=frozenset({tree_scope(tree.tree_id)}),
                    based_on=node.observed_frontier,
                    data={
                        "tree_id": tree.tree_id,
                        "node_id": node.node_id,
                        "model": node.model,
                        "role": response.role,
                    },
                )
            return await self._fail_node(tree, node.node_id, reason)
        model_commit: WorldCommit | None = None
        if self._world is not None:
            assert self._world_effects is not None
            model_commit = await self._world_effects.append_commit(
                commit_id=f"{prefix}:completed",
                kind=MODEL_COMPLETED,
                summary=f"模型完成：{node.model}",
                scopes=frozenset({tree_scope(tree.tree_id)}),
                based_on=node.observed_frontier,
                data={
                    "tree_id": tree.tree_id,
                    "node_id": node.node_id,
                    "model": node.model,
                    "content_length": len(response.content),
                    "tool_call_count": len(response.tool_calls),
                },
            )
        tree = tree.append(node.node_id, response)
        _logger.debug(
            "模型步骤完成 tree_id=%s node_id=%s tool_call_count=%d",
            tree.tree_id,
            node.node_id,
            len(response.tool_calls),
        )
        if model_commit is not None:
            tree = tree.advance_frontier(node.node_id, WorldFrontier(model_commit.scopes))
        tree = self._publish(tree, observer)
        if response.tool_calls:
            return tree
        return self._publish(await self._complete_node(tree, node.node_id, response.content), observer)

    async def _execute_pending(self, tree: AgentTree, node_id: str, calls: tuple[ToolCall, ...]) -> AgentTree:
        """检查并封口一个 assistant Tool batch，随后只执行其中的下一个调用。"""
        node = tree.node(node_id)
        if self._world is not None and not set(call.call_id for call in calls) <= node.sealed_call_ids:
            try:
                scopes = self._resolve_scopes(calls)
            except Exception as error:
                return await self._reject_scope_batch(tree, node_id, calls, error)
            if not node.reviewed_world_update:
                tool_scopes = {scope for item in scopes.values() for scope in item.observe}
                observe_scopes = frozenset(set(node.observed_frontier.positions) | tool_scopes)
                delta = await self._world.delta(node.observed_frontier, observe_scopes)
                if delta.commits:
                    assert self._world_effects is not None
                    await self._world_effects.record_delta_delivered(
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
            assert self._world_effects is not None
            requested = await self._world_effects.record_tool_requests(tree, node_id, calls, scopes)
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
        if self._world is not None:
            assert self._world_effects is not None
            for call in calls:
                await self._world_effects.append_commit(
                    commit_id=f"{tree.tree_id}:{node_id}:{call.call_id}:scope-error",
                    kind=TOOL_FAILED,
                    summary=f"工具 scope 解析失败：{call.name}",
                    scopes=frozenset({tree_scope(tree.tree_id)}),
                    based_on=tree.node(node_id).observed_frontier,
                    data={
                        "tree_id": tree.tree_id,
                        "node_id": node_id,
                        "tool_call_id": call.call_id,
                        "tool": call.name,
                        "error": str(error),
                        "status": ToolStatus.FAILED.value,
                    },
                )
        rejected = tree
        for call in calls:
            rejected = rejected.append(
                node_id,
                ChatMessage.tool(call.call_id, f"工具 scope 解析失败：{error}", is_error=True),
            )
        return rejected

    def _resolve_scopes(self, calls: tuple[ToolCall, ...]) -> dict[str, ToolScopes]:
        scopes: dict[str, ToolScopes] = {}
        for call in calls:
            resolved = self._tools.scopes_for(call)
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
        result = await self._tools.execute(call)
        if isinstance(result, ToolOutput):
            return await self._append_tool_output(tree, node_id, call, result)
        delegated, rejection = await self._apply_delegation(tree, node_id, call, result)
        if rejection is not None:
            return await self._append_tool_output(tree, node_id, call, rejection)
        return delegated

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
            "AgentNode 已委派 tree_id=%s parent_id=%s child_agent=%s",
            tree.tree_id,
            node_id,
            request.agent,
        )
        if self._world is not None:
            assert self._world_effects is not None
            child = spawned.node(f"{tree.tree_id}:{len(tree.nodes)}")
            await self._world_effects.record_node_spawned(tree, child)
        return spawned, None

    async def _append_tool_output(
        self,
        tree: AgentTree,
        node_id: str,
        call: ToolCall,
        output: ToolOutput,
    ) -> AgentTree:
        if self._world is not None:
            assert self._world_effects is not None
            node = tree.node(node_id)
            scopes = node.sealed_call_scopes.get(call.call_id, ToolScopes())
            frontier = await self._world_effects.record_tool_output(tree, node_id, call, output, scopes)
            tree = tree.advance_frontier(node_id, frontier)
        return tree.append(node_id, ChatMessage.tool(call.call_id, output.content, is_error=output.is_error))

    async def _complete_node(self, tree: AgentTree, node_id: str, result: str) -> AgentTree:
        node = tree.node(node_id)
        if self._world is not None and not node.reviewed_world_update:
            delta = await self._world.delta(node.observed_frontier, frozenset(node.observed_frontier.positions))
            if delta.commits:
                assert self._world_effects is not None
                await self._world_effects.record_delta_delivered(
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
        if self._world is not None:
            assert self._world_effects is not None
            frontier = await self._world_effects.record_root_completion(tree, node_id, result)
            tree = tree.advance_frontier(node_id, frontier)
        return tree.complete(node_id, result)

    async def _fail_node(self, tree: AgentTree, node_id: str, error: str) -> AgentTree:
        node = tree.node(node_id)
        if node.parent_id is None:
            if self._world is not None:
                assert self._world_effects is not None
                await self._world_effects.record_tree_failed(
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
        if self._world is None:
            return tree
        assert self._world_effects is not None and child.parent_id is not None
        frontier = await self._world_effects.record_delegation_completion(tree, child, content, is_error=is_error)
        return tree.advance_frontier(child.parent_id, frontier)

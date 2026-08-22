"""AgentTree 的确定性单循环运行时。"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from src.contracts import (
    AgentNode,
    AgentTree,
    ChatMessage,
    DelegationRequest,
    Model,
    ModelRequest,
    ToolCall,
    ToolOutput,
    ToolScopes,
    TreeStatus,
    WorldCommit,
    WorldCommitInput,
    WorldDeltaPage,
    WorldFrontier,
    WorldJournal,
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
        world: WorldJournal | None = None,
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
        self._max_depth = max_depth
        self._max_nodes = max_nodes
        self._max_steps = max_steps

    async def run(self, tree: AgentTree, observer: Callable[[AgentTree], None] | None = None) -> AgentTree:
        self._validate_definitions(tree)
        if self._world is not None:
            await self._world.initialize()
        current = self._publish(tree, observer)
        for _ in range(self._max_steps):
            if current.status != TreeStatus.RUNNING:
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
            try:
                definitions = self._tools.definitions_for(node.tools)
                response = await self._model.complete(
                    ModelRequest(node.model, self._assembler.assemble(current, node.node_id), definitions)
                )
            except Exception as error:
                failed = await self._fail_node(current, node.node_id, f"model failed: {error}")
                current = self._publish(failed, observer)
                continue
            if response.role != "assistant":
                current = self._publish(
                    await self._fail_node(current, node.node_id, "model must return an assistant message"), observer
                )
                continue
            current = self._publish(current.append(node.node_id, response), observer)
            if not response.tool_calls:
                current = self._publish(await self._complete_node(current, node.node_id, response.content), observer)
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

    async def _execute_pending(self, tree: AgentTree, node_id: str, calls: tuple[ToolCall, ...]) -> AgentTree:
        """检查并封口一个 assistant Tool batch，随后只执行其中的下一个调用。"""
        node = tree.node(node_id)
        if self._world is not None and not set(call.call_id for call in calls) <= node.sealed_call_ids:
            try:
                scopes = self._resolve_scopes(calls)
            except Exception as error:
                return self._reject_scope_batch(tree, node_id, calls, error)
            if not node.reviewed_world_update:
                tool_scopes = {scope for item in scopes.values() for scope in item.observe}
                observe_scopes = frozenset(set(node.observed_frontier.positions) | tool_scopes)
                delta = await self._world.delta(node.observed_frontier, observe_scopes)
                if delta.commits:
                    return tree.defer_tools_for_world(
                        node_id,
                        tuple(call.call_id for call in calls),
                        self._render_delta(delta),
                        delta.end,
                        reviewed=not delta.has_more,
                    )
            requested = await self._record_tool_requests(tree, node_id, calls, scopes)
            tree = tree.advance_frontier(node_id, requested).seal_calls(
                node_id,
                tuple(call.call_id for call in calls),
                scopes,
            )
        return await self._execute_call(tree, node_id, calls[0])

    @staticmethod
    def _reject_scope_batch(
        tree: AgentTree,
        node_id: str,
        calls: tuple[ToolCall, ...],
        error: Exception,
    ) -> AgentTree:
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
                ToolOutput(f"当前 Agent 不可见此工具：{call.name}", is_error=True),
            )
        result = await self._tools.execute(call)
        if isinstance(result, ToolOutput):
            return await self._append_tool_output(tree, node_id, call, result)
        delegated, rejection = self._apply_delegation(tree, node_id, call, result)
        if rejection is not None:
            return await self._append_tool_output(tree, node_id, call, rejection)
        return delegated

    def _apply_delegation(
        self,
        tree: AgentTree,
        node_id: str,
        call: ToolCall,
        request: DelegationRequest,
    ) -> tuple[AgentTree, ToolOutput | None]:
        parent = self._agents.get(tree.node(node_id).definition_id)
        if request.agent not in parent.children:
            return tree, ToolOutput(f"当前 Agent 不允许委派给：{request.agent}", is_error=True)
        if len(tree.nodes) >= self._max_nodes:
            return tree, ToolOutput("AgentTree 已达到节点数上限", is_error=True)
        if tree.depth(node_id) >= self._max_depth:
            return tree, ToolOutput("AgentTree 已达到深度上限", is_error=True)
        return tree.spawn(node_id, call, self._agents.get(request.agent), request.instruction), None

    async def _append_tool_output(
        self,
        tree: AgentTree,
        node_id: str,
        call: ToolCall,
        output: ToolOutput,
    ) -> AgentTree:
        if self._world is not None:
            node = tree.node(node_id)
            scopes = node.sealed_call_scopes.get(call.call_id, ToolScopes())
            commit = await self._world.append_commit(
                commit_id=f"{tree.tree_id}:{node_id}:{call.call_id}:result",
                kind="tool.failed" if output.is_error else "tool.succeeded",
                source="engine",
                summary=f"工具{'失败' if output.is_error else '完成'}：{call.name}",
                scopes=self._publish_scopes(tree, scopes),
                based_on=node.observed_frontier,
                data={
                    "tree_id": tree.tree_id,
                    "node_id": node_id,
                    "tool_call_id": call.call_id,
                    "tool": call.name,
                    "content": output.content,
                    "is_error": output.is_error,
                },
            )
            tree = tree.advance_frontier(node_id, WorldFrontier(commit.scopes))
        return tree.append(node_id, ChatMessage.tool(call.call_id, output.content, is_error=output.is_error))

    async def _record_tool_requests(
        self,
        tree: AgentTree,
        node_id: str,
        calls: tuple[ToolCall, ...],
        scopes: dict[str, ToolScopes],
    ) -> WorldFrontier:
        assert self._world is not None
        node = tree.node(node_id)
        commits = await self._world.append_commits(
            tuple(
                WorldCommitInput(
                    commit_id=f"{tree.tree_id}:{node_id}:{call.call_id}:requested",
                    kind="tool.requested",
                    source="engine",
                    summary=f"Agent 请求工具：{call.name}",
                    scopes=self._publish_scopes(tree, scopes[call.call_id]),
                    based_on=node.observed_frontier,
                    data={
                        "tree_id": tree.tree_id,
                        "node_id": node_id,
                        "tool_call_id": call.call_id,
                        "tool": call.name,
                        "arguments": dict(call.arguments),
                    },
                )
                for call in calls
            )
        )
        return self._frontier_for(commits)

    async def _complete_node(self, tree: AgentTree, node_id: str, result: str) -> AgentTree:
        node = tree.node(node_id)
        if self._world is not None and not node.reviewed_world_update:
            delta = await self._world.delta(node.observed_frontier, frozenset(node.observed_frontier.positions))
            if delta.commits:
                return tree.observe(
                    node_id,
                    ChatMessage.message(self._render_delta(delta)),
                    delta.end,
                    reviewed=not delta.has_more,
                )
        if node.parent_id is not None:
            completed = tree.complete(node_id, result)
            return await self._record_delegation_completion(completed, node, result, is_error=False)
        if self._world is not None:
            commits = await self._world.append_commits(
                (
                    WorldCommitInput(
                        f"{tree.tree_id}:{node_id}:output:requested",
                        "output.requested",
                        "engine",
                        "root 请求发布回复",
                        self._publish_scopes(tree, ToolScopes()),
                        node.observed_frontier,
                        {"tree_id": tree.tree_id, "node_id": node_id, "content": result},
                    ),
                    WorldCommitInput(
                        f"{tree.tree_id}:{node_id}:output:committed",
                        "output.committed",
                        "engine",
                        "root 已发布回复",
                        self._publish_scopes(tree, ToolScopes()),
                        node.observed_frontier,
                        {"tree_id": tree.tree_id, "node_id": node_id, "content": result},
                    ),
                )
            )
            tree = tree.advance_frontier(node_id, self._frontier_for(commits))
        return tree.complete(node_id, result)

    async def _fail_node(self, tree: AgentTree, node_id: str, error: str) -> AgentTree:
        node = tree.node(node_id)
        failed = tree.fail(node_id, error)
        if node.parent_id is None:
            return failed
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
        assert child.parent_id is not None and child.parent_call_id is not None
        commit = await self._world.append_commit(
            commit_id=f"{tree.tree_id}:{child.parent_id}:{child.parent_call_id}:result",
            kind="tool.failed" if is_error else "tool.succeeded",
            source="engine",
            summary=f"委派 Agent {'失败' if is_error else '完成'}：{child.node_id}",
            scopes=self._publish_scopes(tree, ToolScopes()),
            based_on=child.observed_frontier,
            data={
                "tree_id": tree.tree_id,
                "node_id": child.parent_id,
                "tool_call_id": child.parent_call_id,
                "child_node_id": child.node_id,
                "content": content,
                "is_error": is_error,
            },
        )
        return tree.advance_frontier(child.parent_id, WorldFrontier(commit.scopes))

    @staticmethod
    def _frontier_for(commits: tuple[WorldCommit, ...]) -> WorldFrontier:
        positions: dict[str, int] = {}
        for commit in commits:
            for scope, sequence in commit.scopes.items():
                positions[scope] = max(positions.get(scope, 0), sequence)
        return WorldFrontier(positions)

    @staticmethod
    def _render_delta(delta: WorldDeltaPage) -> str:
        payload = {
            "kind": "world.delta",
            "commits": [
                {
                    "id": commit.commit_id,
                    "kind": commit.kind,
                    "source": commit.source,
                    "summary": commit.summary,
                    "scopes": dict(commit.scopes),
                }
                for commit in delta.commits
            ],
            "has_more": delta.has_more,
        }
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def _publish_scopes(tree: AgentTree, scopes: ToolScopes) -> frozenset[str]:
        return frozenset({f"aurora:tree:{tree.tree_id}", *scopes.publish})

"""AgentTree 运行时的世界事件记录与投影辅助。"""

from __future__ import annotations

import json
from types import MappingProxyType
from typing import TYPE_CHECKING

from aurora_bot.contracts import ToolScopes, ToolStatus, WorldCommitInput, WorldFrontier
from aurora_bot.contracts.memory_codec import exposure_data
from aurora_bot.contracts.resource import ResourceInstance
from aurora_bot.contracts.resource_codec import resource_instance_data, resource_ref_data
from aurora_bot.contracts.tree_lifecycle import TREE_COMPLETED, TREE_FAILED, TREE_STARTED, tree_scope
from aurora_bot.engine.events import (
    MODEL_COMPLETED,
    MODEL_FAILED,
    MODEL_REQUESTED,
    NODE_COMPLETED,
    NODE_FAILED,
    NODE_SPAWNED,
    OUTPUT_COMMITTED,
    OUTPUT_REQUESTED,
    TOOL_FAILED,
    TOOL_REQUESTED,
    TOOL_SUCCEEDED,
    TOOL_UNKNOWN,
    WORLD_DELTA_DELIVERED,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from aurora_bot.contracts import (
        AgentNode,
        AgentTree,
        ChatMessage,
        ModelRequest,
        ToolCall,
        ToolDefinition,
        ToolOutput,
        WorldCommit,
        WorldDeltaPage,
    )
    from aurora_bot.contracts.memory import MemoryExposure
    from aurora_bot.contracts.pkgs.world import WorldJournal
    from aurora_bot.contracts.process import CognitionProcess

_TOOL_EVENT_KINDS = {
    ToolStatus.SUCCEEDED: TOOL_SUCCEEDED,
    ToolStatus.FAILED: TOOL_FAILED,
    ToolStatus.UNKNOWN: TOOL_UNKNOWN,
}
_TOOL_SUMMARY_ACTIONS = {
    ToolStatus.SUCCEEDED: "完成",
    ToolStatus.FAILED: "失败",
    ToolStatus.UNKNOWN: "结果未知",
}


class EngineWorldEffects:
    """只构造并追加 engine 的世界提交，不改变 AgentTree。"""

    def __init__(
        self,
        world: WorldJournal,
        *,
        tools: tuple[ToolDefinition, ...],
        process: CognitionProcess,
        bot_id: str = "aurora:bot/default",
    ) -> None:
        """绑定世界与实际选中的冻结工具接口，不在写入时重新推断版本。"""
        self._world = world
        self._bot_id = bot_id
        self._process = process
        self._tool_refs = MappingProxyType({tool.name: tool.ref for tool in tools})

    def _tool_ref_data(self, tree: AgentTree, node_id: str, name: str | None) -> dict[str, str | None] | None:
        """只记录已经注册且对当前节点可见的接口，其他调用保持版本未知。"""
        if name is None or name not in tree.node(node_id).tools:
            return None
        ref = self._tool_refs.get(name)
        return resource_ref_data(ref) if ref is not None else None

    async def _append(
        self,
        *,
        commit_id: str,
        kind: str,
        summary: str,
        scopes: frozenset[str],
        based_on: WorldFrontier,
        data: Mapping[str, object],
    ) -> WorldCommit:
        return await self._world.append_commit(
            commit_id=commit_id,
            kind=kind,
            source="engine",
            summary=summary,
            scopes=scopes,
            based_on=based_on,
            data=data,
        )

    async def tree_started(self, tree: AgentTree) -> None:
        root = tree.node(tree.root_id)
        instance = ResourceInstance(tree.tree_id, self._bot_id, self._process.ref)
        await self._append(
            commit_id=f"{tree.tree_id}:tree:started",
            kind=TREE_STARTED,
            summary="AgentTree 已启动",
            scopes=frozenset({tree_scope(tree.tree_id)}),
            based_on=root.observed_frontier,
            data={
                "tree_id": tree.tree_id,
                "caused_by": tree.caused_by,
                "bot_id": self._bot_id,
                "root_id": tree.root_id,
                "definition_id": root.definition_id,
                "definition_ref": resource_ref_data(root.definition_ref),
                "process_ref": resource_ref_data(self._process.ref),
                "instance": resource_instance_data(instance),
                "focus_goal_ids": list(root.focus_goal_ids),
                "message": root.messages[0].content,
            },
        )

    async def tree_failed(self, tree: AgentTree, error: str, data: Mapping[str, object]) -> None:
        await self._append(
            commit_id=f"{tree.tree_id}:tree:failed",
            kind=TREE_FAILED,
            summary=f"AgentTree 失败：{error}",
            scopes=frozenset({tree_scope(tree.tree_id)}),
            based_on=tree.node(tree.root_id).observed_frontier,
            data={"tree_id": tree.tree_id, "error": error, **data},
        )

    async def model_requested(
        self, tree: AgentTree, node: AgentNode, request: ModelRequest, *, memory: MemoryExposure | None = None
    ) -> None:
        """模型输入装配成功后保存实际记忆来源，失败请求仍保留尝试事实。"""
        await self._append(
            commit_id=f"{_model_prefix(tree, node)}:requested",
            kind=MODEL_REQUESTED,
            summary=f"请求模型：{node.model}",
            scopes=frozenset({tree_scope(tree.tree_id)}),
            based_on=node.observed_frontier,
            data={
                "tree_id": tree.tree_id,
                "node_id": node.node_id,
                "model": request.model,
                "endpoint_ref": resource_ref_data(request.endpoint.ref),
                "provider_ref": resource_ref_data(request.endpoint.provider.ref),
                "definition_ref": resource_ref_data(node.definition_ref),
                "bot_id": self._bot_id,
                "message_count": len(request.messages),
                "tool_count": len(request.tools),
                "tool_refs": [resource_ref_data(tool.ref) for tool in request.tools],
                "resources": [resource_ref_data(ref) for ref in request.resources],
                "memory": exposure_data(memory) if memory is not None else None,
            },
        )

    async def model_failed(self, tree: AgentTree, node: AgentNode, error: str) -> None:
        await self._append(
            commit_id=f"{_model_prefix(tree, node)}:failed",
            kind=MODEL_FAILED,
            summary=f"模型失败：{error}",
            scopes=frozenset({tree_scope(tree.tree_id)}),
            based_on=node.observed_frontier,
            data={
                "tree_id": tree.tree_id,
                "node_id": node.node_id,
                "model": node.model,
                "error": error,
            },
        )

    async def model_role_invalid(self, tree: AgentTree, node: AgentNode, role: str) -> None:
        reason = "model must return an assistant message"
        await self._append(
            commit_id=f"{_model_prefix(tree, node)}:failed",
            kind=MODEL_FAILED,
            summary=f"模型失败：{reason}",
            scopes=frozenset({tree_scope(tree.tree_id)}),
            based_on=node.observed_frontier,
            data={
                "tree_id": tree.tree_id,
                "node_id": node.node_id,
                "model": node.model,
                "role": role,
            },
        )

    async def model_completed(self, tree: AgentTree, node: AgentNode, response: ChatMessage) -> WorldFrontier:
        commit = await self._append(
            commit_id=f"{_model_prefix(tree, node)}:completed",
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
        return WorldFrontier(commit.scopes)

    async def scope_rejected(
        self,
        tree: AgentTree,
        node_id: str,
        calls: tuple[ToolCall, ...],
        error: Exception,
    ) -> None:
        based_on = tree.node(node_id).observed_frontier
        for call in calls:
            await self._append(
                commit_id=f"{tree.tree_id}:{node_id}:{call.call_id}:scope-error",
                kind=TOOL_FAILED,
                summary=f"工具 scope 解析失败：{call.name}",
                scopes=frozenset({tree_scope(tree.tree_id)}),
                based_on=based_on,
                data={
                    "tree_id": tree.tree_id,
                    "node_id": node_id,
                    "tool_call_id": call.call_id,
                    "tool": call.name,
                    "tool_ref": self._tool_ref_data(tree, node_id, call.name),
                    "error": str(error),
                    "status": ToolStatus.FAILED.value,
                },
            )

    async def delta_delivered(
        self,
        tree: AgentTree,
        node_id: str,
        delta: WorldDeltaPage,
        *,
        commit_id: str,
        call_ids: tuple[str, ...] = (),
    ) -> None:
        await self._append(
            commit_id=commit_id,
            kind=WORLD_DELTA_DELIVERED,
            summary="世界更新已披露给 Agent",
            scopes=frozenset({tree_scope(tree.tree_id)}),
            based_on=delta.start,
            data={
                "tree_id": tree.tree_id,
                "node_id": node_id,
                "call_ids": list(call_ids),
                "commit_count": len(delta.commits),
                "has_more": delta.has_more,
            },
        )

    async def node_spawned(self, tree: AgentTree, child: AgentNode) -> None:
        await self._append(
            commit_id=f"{tree.tree_id}:{child.node_id}:spawned",
            kind=NODE_SPAWNED,
            summary=f"委派创建节点：{child.definition_id}",
            scopes=frozenset({tree_scope(tree.tree_id)}),
            based_on=child.observed_frontier,
            data={
                "tree_id": tree.tree_id,
                "node_id": child.node_id,
                "parent_id": child.parent_id,
                "tool_call_id": child.parent_call_id,
                "definition_id": child.definition_id,
                "definition_ref": resource_ref_data(child.definition_ref),
            },
        )

    async def tool_output(
        self,
        tree: AgentTree,
        node_id: str,
        call: ToolCall,
        output: ToolOutput,
        scopes: ToolScopes,
    ) -> WorldFrontier:
        commit = await self._append(
            commit_id=f"{tree.tree_id}:{node_id}:{call.call_id}:result",
            kind=_TOOL_EVENT_KINDS[output.status],
            summary=f"工具{_TOOL_SUMMARY_ACTIONS[output.status]}：{call.name}",
            scopes=publish_scopes(tree, scopes),
            based_on=tree.node(node_id).observed_frontier,
            data={
                "tree_id": tree.tree_id,
                "node_id": node_id,
                "tool_call_id": call.call_id,
                "tool": call.name,
                "tool_ref": self._tool_ref_data(tree, node_id, call.name),
                "content": output.content,
                "is_error": output.is_error,
                "status": output.status.value,
                "evidence_refs": list(output.evidence_refs),
            },
        )
        return WorldFrontier(commit.scopes)

    async def tool_requests(
        self,
        tree: AgentTree,
        node_id: str,
        calls: tuple[ToolCall, ...],
        scopes: Mapping[str, ToolScopes],
    ) -> WorldFrontier:
        node = tree.node(node_id)
        commits = await self._world.append_commits(
            tuple(
                WorldCommitInput(
                    commit_id=f"{tree.tree_id}:{node_id}:{call.call_id}:requested",
                    kind=TOOL_REQUESTED,
                    source="engine",
                    summary=f"Agent 请求工具：{call.name}",
                    scopes=publish_scopes(tree, scopes[call.call_id]),
                    based_on=node.observed_frontier,
                    data={
                        "tree_id": tree.tree_id,
                        "node_id": node_id,
                        "tool_call_id": call.call_id,
                        "tool": call.name,
                        "tool_ref": self._tool_ref_data(tree, node_id, call.name),
                        "arguments": dict(call.arguments),
                    },
                )
                for call in calls
            )
        )
        return frontier_for(commits)

    async def root_completion(self, tree: AgentTree, node_id: str, result: str) -> WorldFrontier:
        node = tree.node(node_id)
        scopes = publish_scopes(tree, ToolScopes())
        data = {"tree_id": tree.tree_id, "node_id": node_id, "content": result}
        commits = await self._world.append_commits(
            (
                WorldCommitInput(
                    f"{tree.tree_id}:{node_id}:output:requested",
                    OUTPUT_REQUESTED,
                    "engine",
                    "root 请求发布回复",
                    scopes,
                    node.observed_frontier,
                    data,
                ),
                WorldCommitInput(
                    f"{tree.tree_id}:{node_id}:output:committed",
                    OUTPUT_COMMITTED,
                    "engine",
                    "root 已发布回复",
                    scopes,
                    node.observed_frontier,
                    data,
                ),
                WorldCommitInput(
                    f"{tree.tree_id}:tree:completed",
                    TREE_COMPLETED,
                    "engine",
                    "AgentTree 已完成",
                    scopes,
                    node.observed_frontier,
                    data,
                ),
            )
        )
        return frontier_for(commits)

    async def delegation_completion(
        self,
        tree: AgentTree,
        child: AgentNode,
        content: str,
        *,
        is_error: bool,
    ) -> WorldFrontier:
        assert child.parent_id is not None and child.parent_call_id is not None
        parent = tree.node(child.parent_id)
        tool = next(
            (
                call.name
                for message in parent.messages
                for call in message.tool_calls
                if call.call_id == child.parent_call_id
            ),
            None,
        )
        tool_status = ToolStatus.FAILED if is_error else ToolStatus.SUCCEEDED
        commits = await self._world.append_commits(
            (
                WorldCommitInput(
                    f"{tree.tree_id}:{child.node_id}:{'failed' if is_error else 'completed'}",
                    NODE_FAILED if is_error else NODE_COMPLETED,
                    "engine",
                    f"Agent 节点{'失败' if is_error else '完成'}：{child.definition_id}",
                    frozenset({tree_scope(tree.tree_id)}),
                    child.observed_frontier,
                    {
                        "tree_id": tree.tree_id,
                        "node_id": child.node_id,
                        "definition_id": child.definition_id,
                        "error" if is_error else "result": content,
                    },
                ),
                WorldCommitInput(
                    f"{tree.tree_id}:{child.parent_id}:{child.parent_call_id}:result",
                    TOOL_FAILED if is_error else TOOL_SUCCEEDED,
                    "engine",
                    f"委派 Agent {'失败' if is_error else '完成'}：{child.node_id}",
                    frozenset({tree_scope(tree.tree_id)}),
                    child.observed_frontier,
                    {
                        "tree_id": tree.tree_id,
                        "node_id": child.parent_id,
                        "tool_call_id": child.parent_call_id,
                        "child_node_id": child.node_id,
                        "tool": tool,
                        "tool_ref": self._tool_ref_data(tree, child.parent_id, tool),
                        "content": content,
                        "is_error": is_error,
                        "status": tool_status.value,
                    },
                ),
            )
        )
        return frontier_for(commits)


def _model_prefix(tree: AgentTree, node: AgentNode) -> str:
    step_index = sum(message.role == "assistant" for message in node.messages)
    return f"{tree.tree_id}:{node.node_id}:model:{step_index}"


def frontier_for(commits: tuple[WorldCommit, ...]) -> WorldFrontier:
    """把一批提交投影为各 scope 的最高序号。"""
    positions: dict[str, int] = {}
    for commit in commits:
        for scope, sequence in commit.scopes.items():
            positions[scope] = max(positions.get(scope, 0), sequence)
    return WorldFrontier(positions)


def render_delta(delta: WorldDeltaPage) -> str:
    """把世界增量渲染成稳定、紧凑的模型输入。"""
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


def publish_scopes(tree: AgentTree, scopes: ToolScopes) -> frozenset[str]:
    """合并树 scope 与工具声明的发布 scope。"""
    return frozenset({tree_scope(tree.tree_id), *scopes.publish})

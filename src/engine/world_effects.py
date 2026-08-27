"""AgentTree 运行时的世界事件记录与投影辅助。"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from src.contracts import (
    NODE_COMPLETED,
    NODE_FAILED,
    NODE_SPAWNED,
    OUTPUT_COMMITTED,
    OUTPUT_REQUESTED,
    TOOL_FAILED,
    TOOL_REQUESTED,
    TOOL_SUCCEEDED,
    TOOL_UNKNOWN,
    TREE_COMPLETED,
    TREE_FAILED,
    TREE_STARTED,
    WORLD_DELTA_DELIVERED,
    ToolScopes,
    ToolStatus,
    WorldCommitInput,
    WorldFrontier,
    tree_scope,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from src.contracts import AgentNode, AgentTree, ToolCall, ToolOutput, WorldCommit, WorldDeltaPage, WorldJournal

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

    def __init__(self, world: WorldJournal) -> None:
        self._world = world

    async def append_commit(
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

    async def record_tree_started(self, tree: AgentTree) -> None:
        root = tree.node(tree.root_id)
        await self.append_commit(
            commit_id=f"{tree.tree_id}:tree:started",
            kind=TREE_STARTED,
            summary="AgentTree 已启动",
            scopes=frozenset({tree_scope(tree.tree_id)}),
            based_on=root.observed_frontier,
            data={
                "tree_id": tree.tree_id,
                "root_id": tree.root_id,
                "definition_id": root.definition_id,
                "message": root.messages[0].content,
            },
        )

    async def record_tree_failed(self, tree: AgentTree, error: str, data: Mapping[str, object]) -> None:
        await self.append_commit(
            commit_id=f"{tree.tree_id}:tree:failed",
            kind=TREE_FAILED,
            summary=f"AgentTree 失败：{error}",
            scopes=frozenset({tree_scope(tree.tree_id)}),
            based_on=tree.node(tree.root_id).observed_frontier,
            data={"tree_id": tree.tree_id, "error": error, **data},
        )

    async def record_delta_delivered(
        self,
        tree: AgentTree,
        node_id: str,
        delta: WorldDeltaPage,
        *,
        commit_id: str,
        call_ids: tuple[str, ...] = (),
    ) -> None:
        await self.append_commit(
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

    async def record_node_spawned(self, tree: AgentTree, child: AgentNode) -> None:
        await self.append_commit(
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
            },
        )

    async def record_tool_output(
        self,
        tree: AgentTree,
        node_id: str,
        call: ToolCall,
        output: ToolOutput,
        scopes: ToolScopes,
    ) -> WorldFrontier:
        commit = await self.append_commit(
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
                "content": output.content,
                "is_error": output.is_error,
                "status": output.status.value,
            },
        )
        return WorldFrontier(commit.scopes)

    async def record_tool_requests(
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
                        "arguments": dict(call.arguments),
                    },
                )
                for call in calls
            )
        )
        return frontier_for(commits)

    async def record_root_completion(self, tree: AgentTree, node_id: str, result: str) -> WorldFrontier:
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

    async def record_delegation_completion(
        self,
        tree: AgentTree,
        child: AgentNode,
        content: str,
        *,
        is_error: bool,
    ) -> WorldFrontier:
        assert child.parent_id is not None and child.parent_call_id is not None
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
                        "content": content,
                        "is_error": is_error,
                        "status": tool_status.value,
                    },
                ),
            )
        )
        return frontier_for(commits)


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

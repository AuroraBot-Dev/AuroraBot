"""把运行时领域对象投影为 ops 与终端使用的 JSON 数据。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ops.router import render_result
from src.utils import thaw_json

if TYPE_CHECKING:
    from ops.contracts import OperationResult
    from src.contracts import (
        AgentDefinition,
        AgentNode,
        AgentTree,
        ChatMessage,
        ToolDefinition,
        TreeActivity,
        WorldCommit,
    )
    from src.mcp import McpAppSnapshot


def agent_dict(definition: AgentDefinition) -> dict[str, Any]:
    """投影一个不可变智能体定义。"""
    return {
        "definition_id": definition.definition_id,
        "description": definition.description,
        "prompt": definition.prompt_id,
        "model": definition.model,
        "tools": sorted(definition.tools),
        "children": sorted(definition.children),
    }


def tool_dict(definition: ToolDefinition) -> dict[str, Any]:
    """投影工具定义，并把冻结 JSON 恢复为普通容器。"""
    return {
        "name": definition.name,
        "description": definition.description,
        "parameters": thaw_json(definition.parameters),
    }


def mcp_app_dict(snapshot: McpAppSnapshot) -> dict[str, Any]:
    """投影单个 MCP App 的运行快照。"""
    return {
        "package": snapshot.package,
        "configured_enabled": snapshot.configured_enabled,
        "active": snapshot.active,
        "transport": snapshot.transport.value,
        "state": snapshot.state.value,
        "negotiated_version": snapshot.negotiated_version,
        "tool_ids": list(snapshot.tool_ids),
        "last_error": snapshot.last_error,
        "restart_required": snapshot.restart_required,
    }


def terminal_text(result: OperationResult, *, command: bool) -> tuple[str, bool]:
    """把 ops 结果压缩为终端文本及树失败标记。"""
    if command or not result.ok or result.data is None:
        return render_result(result), False
    root_id = result.data.get("root_id")
    nodes = result.data.get("nodes")
    if not isinstance(root_id, str) or not isinstance(nodes, list):
        return render_result(result), False
    root = next((node for node in nodes if isinstance(node, dict) and node.get("node_id") == root_id), None)
    if root is None:
        return render_result(result), False
    failed = root.get("status") == "failed"
    text = root.get("error") if failed else root.get("result")
    return str(text) if text is not None else render_result(result), failed


def tree_summary(tree: AgentTree) -> dict[str, Any]:
    """投影 AgentTree 的有界摘要。"""
    return {
        "tree_id": tree.tree_id,
        "root_id": tree.root_id,
        "status": tree.status.value,
        "node_count": len(tree.nodes),
    }


def tree_dict(tree: AgentTree) -> dict[str, Any]:
    """投影 AgentTree 及其全部节点。"""
    return {**tree_summary(tree), "nodes": [node_dict(node) for node in tree.nodes]}


def node_dict(node: AgentNode) -> dict[str, Any]:
    """投影一个 AgentNode。"""
    return {
        "node_id": node.node_id,
        "parent_id": node.parent_id,
        "parent_call_id": node.parent_call_id,
        "definition_id": node.definition_id,
        "prompt_id": node.prompt_id,
        "model": node.model,
        "tools": sorted(node.tools),
        "status": node.status.value,
        "result": node.result,
        "error": node.error,
        "messages": [message_dict(message) for message in node.messages],
        "observed_frontier": dict(node.observed_frontier.positions),
        "reviewed_world_update": node.reviewed_world_update,
    }


def message_dict(message: ChatMessage) -> dict[str, Any]:
    """投影一条四角色领域消息。"""
    return {
        "role": message.role,
        "content": message.content,
        "tool_call_id": message.tool_call_id,
        "is_error": message.is_error,
        "tool_calls": [
            {"call_id": call.call_id, "name": call.name, "arguments": dict(call.arguments)}
            for call in message.tool_calls
        ],
    }


def commit_dict(commit: WorldCommit) -> dict[str, Any]:
    """投影一条世界提交。"""
    return {
        "commit_id": commit.commit_id,
        "kind": commit.kind,
        "source": commit.source,
        "summary": commit.summary,
        "occurred_at": commit.occurred_at.isoformat(),
        "scopes": dict(commit.scopes),
        "based_on": dict(commit.based_on.positions),
        "data": dict(commit.data),
    }


def activity_dict(activity: TreeActivity) -> dict[str, Any]:
    """投影世界日志推导出的树活动摘要。"""
    return {
        "tree_id": activity.tree_id,
        "commit_count": activity.commit_count,
        "first_seen": activity.first_seen.isoformat(),
        "last_seen": activity.last_seen.isoformat(),
    }

"""投影 Assembly 中的领域对象为 ops JSON 数据。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.utils import thaw_json

if TYPE_CHECKING:
    from src.contracts import AgentDefinition, McpAppSnapshot, ToolDefinition, WorldCommit


def utils_status() -> dict[str, Any]:
    """返回无项目语义的共享工具能力目录。"""
    return {
        "logging": ["configure_logging", "configure_console_logging", "console_logging_status", "get_logger"],
        "serialization": ["extract_json_from_text", "freeze_json", "thaw_json"],
        "text": ["bounded_summary"],
        "time": ["utc_now", "utc_today"],
    }


def contracts_status() -> dict[str, Any]:
    """返回公共契约的稳定能力目录。"""
    return {
        "value_objects": [
            "AgentDefinition",
            "AgentNode",
            "AgentTree",
            "ChatMessage",
            "ModelRequest",
            "ToolCall",
            "ToolDefinition",
            "ToolOutput",
            "WorldCommit",
            "WorldCommitInput",
            "WorldDeltaPage",
            "WorldFrontier",
            "WorldStreamPage",
        ],
        "ports": ["Model", "Tool", "ScopedTool", "WorldReader", "WorldWriter", "WorldJournal"],
    }


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
    """投影工具定义，并恢复冻结 JSON 为普通容器。"""
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

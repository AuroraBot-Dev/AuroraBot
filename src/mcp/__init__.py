"""MCP Python SDK 2.x 客户端适配。"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.mcp.client import (
        TOOL_CONTRACT_EXTENSION,
        WORLD_EVENT_NOTIFICATION,
        WORLD_EVENTS_EXTENSION,
        McpClientFactory,
        McpClientPort,
        SdkMcpClientFactory,
    )
    from src.mcp.models import (
        McpAppSnapshot,
        McpAppSpec,
        McpAppState,
        McpCallRejectedError,
        McpCallResult,
        McpCallUnknownError,
        McpContentBlock,
        McpEventMode,
        McpInboundEvent,
        McpRemoteTool,
        McpRuntimeSnapshot,
        McpStartupError,
        McpToolsPage,
        McpTransport,
    )
    from src.mcp.runtime import McpRuntime, prepare_mcp
    from src.mcp.tool import McpTool, McpToolBinding, bind_mcp_tool

__all__ = [
    "TOOL_CONTRACT_EXTENSION",
    "WORLD_EVENTS_EXTENSION",
    "WORLD_EVENT_NOTIFICATION",
    "McpAppSnapshot",
    "McpAppSpec",
    "McpAppState",
    "McpCallRejectedError",
    "McpCallResult",
    "McpCallUnknownError",
    "McpClientFactory",
    "McpClientPort",
    "McpContentBlock",
    "McpEventMode",
    "McpInboundEvent",
    "McpRemoteTool",
    "McpRuntime",
    "McpRuntimeSnapshot",
    "McpStartupError",
    "McpTool",
    "McpToolBinding",
    "McpToolsPage",
    "McpTransport",
    "SdkMcpClientFactory",
    "bind_mcp_tool",
    "prepare_mcp",
]

_CLIENT = (
    "TOOL_CONTRACT_EXTENSION",
    "WORLD_EVENT_NOTIFICATION",
    "WORLD_EVENTS_EXTENSION",
    "McpClientFactory",
    "McpClientPort",
    "SdkMcpClientFactory",
)
_MODELS = (
    "McpAppSnapshot",
    "McpAppSpec",
    "McpAppState",
    "McpCallRejectedError",
    "McpCallResult",
    "McpCallUnknownError",
    "McpContentBlock",
    "McpEventMode",
    "McpInboundEvent",
    "McpRemoteTool",
    "McpRuntimeSnapshot",
    "McpStartupError",
    "McpToolsPage",
    "McpTransport",
)
_RUNTIME = ("McpRuntime", "prepare_mcp")
_TOOL = ("McpTool", "McpToolBinding", "bind_mcp_tool")

_EXPORTS = {
    **dict.fromkeys(_CLIENT, "src.mcp.client"),
    **dict.fromkeys(_MODELS, "src.mcp.models"),
    **dict.fromkeys(_RUNTIME, "src.mcp.runtime"),
    **dict.fromkeys(_TOOL, "src.mcp.tool"),
}


def __getattr__(name: str) -> object:
    """惰性解析公共出口，避免仅导入配置形状就加载 MCP SDK。"""
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"模块 {__name__!r} 没有属性 {name!r}")
    return getattr(import_module(module_name), name)

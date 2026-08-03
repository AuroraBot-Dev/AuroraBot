"""MCP Kit — AuroraBot Platform 的 MCP 接入包。

导出自描述 ``_create``，组合根通过统一协议完成创建、工具绑定与任务调度。

作者: [Churk-Ben](https://github.com/Churk-Ben)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.platform.mcp.adapter import MCPPlatform

if TYPE_CHECKING:
    from src.contracts.configuration import McpPreference
    from src.platform import PlatformHandle

__all__ = ["MCPPlatform"]


async def _create(_config: object, runtime: object) -> "PlatformHandle":
    """创建 MCP 平台句柄：启动所有 Server 连接、发现 Tool 并构建能力目录。"""
    from src.platform import PlatformHandle

    config = getattr(runtime, "configuration")  # noqa: B009  # type: ignore[union-attr]
    pref: "McpPreference" = config.preference.mcp  # type: ignore[union-attr]
    mcp = MCPPlatform(config, terminal_logs=pref.terminal_logs)  # type: ignore[arg-type]
    catalog = await mcp.start(runtime)  # type: ignore[arg-type]

    bindings = _build_mcp_bindings(mcp, catalog)
    return PlatformHandle(
        bindings=bindings,
        cleanup=mcp.shutdown,
        spawn=None,
    )


def _build_mcp_bindings(mcp: MCPPlatform, catalog: object) -> tuple:
    """从 MCP 能力目录构建工具绑定元组。"""
    from src.contracts.tool import ToolExecutorBinding

    return tuple(
        ToolExecutorBinding(
            capability,
            mcp,
            source_app="platform.mcp",
            source_instance=mcp.source_instance_for(capability.id),
        )
        for capability in catalog.capabilities  # type: ignore[attr-defined]
    )

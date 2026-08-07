"""MCP Kit — AuroraBot Platform 的 MCP 接入包。

导出自描述 ``_create``，组合根通过统一协议完成创建、工具绑定与任务调度。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.platform.mcp.adapter import MCPPlatform

if TYPE_CHECKING:
    from src.contracts.agent import CapabilityCatalogSnapshot
    from src.contracts.configuration import AuroraConfig
    from src.contracts.platform import PlatformHandle, PlatformRuntimePort
    from src.contracts.tool import ToolExecutorBinding

__all__ = ["MCPPlatform"]


async def _create(config: "AuroraConfig", runtime: "PlatformRuntimePort") -> "PlatformHandle":
    """创建 MCP 平台句柄：启动所有 Server 连接、发现 Tool 并构建能力目录。"""
    from src.contracts.platform import PlatformHandle

    mcp = MCPPlatform(config, terminal_logs=config.preference.mcp.terminal_logs)
    catalog = await mcp.start(runtime)

    bindings = _build_mcp_bindings(mcp, catalog)
    return PlatformHandle(
        bindings=bindings,
        cleanup=mcp.shutdown,
        background=mcp.run,
    )


def _build_mcp_bindings(mcp: MCPPlatform, catalog: "CapabilityCatalogSnapshot") -> tuple["ToolExecutorBinding", ...]:
    """从 MCP 能力目录构建工具绑定元组。"""
    from src.contracts.tool import ToolExecutorBinding

    return tuple(
        ToolExecutorBinding(
            capability,
            mcp,
            source_app="platform.mcp",
            source_instance=mcp.source_instance_for(capability.id),
        )
        for capability in catalog.capabilities
    )

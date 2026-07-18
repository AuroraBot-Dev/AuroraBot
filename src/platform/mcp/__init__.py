"""MCP Kit — AuroraBot Platform 的 MCP 接入包。

提供 MCP Server 生命周期管理、Client 连接管理、AMP 消息协议、
Tool schema 转换等基础设施。

作者: [Churk-Ben](https://github.com/Churk-Ben)
"""

from __future__ import annotations

from src.platform.mcp.adapter import MCPPlatform

__all__ = ["MCPPlatform"]

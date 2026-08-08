"""MCP Server 启动规范。

由已校验的 ``config/apps.toml`` App 配置构造。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True, slots=True)
class MCPServerSpec:
    """MCP Server 的完整描述。

    本地进程管理只接受 ``stdio``；远程 Streamable HTTP 由 ClientManager
    直接连接，不创建本地 ServerSpec。
    """

    key: str
    """全局唯一标识，使用 App package。"""

    package: str
    """Python 包名，如 ``org.aurora.weather``。"""

    name: str
    """人类可读名称，如 ``天气应用``。"""

    directory: Path = Path()
    """App 目录路径。"""

    command: list[str] = field(default_factory=list)
    """启动命令，如 ``["uv", "run", "python", "-m", "apps.aurora-app-diary.mcp_server"]``。"""

    args: list[str] = field(default_factory=list)
    """额外命令行参数。"""

    env: dict[str, str] = field(default_factory=dict)
    """环境变量。"""

    enabled: bool = True
    """是否启用。"""

    health_poll_seconds: float = 10.0
    """健康检查轮询间隔秒数。"""

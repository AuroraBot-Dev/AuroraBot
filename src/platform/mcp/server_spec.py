"""MCP Server 规范定义。

由一个 App 的 manifest.yaml + apps/config.yml 合并得出完整启动配置。

作者: [Churk-Ben](https://github.com/Churk-Ben)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(slots=True)
class MCPServerSpec:
    """MCP Server 的完整描述。

    由 manifest.yaml + apps/config.yml 合并得出。
    transport 第一期只允许 ``stdio``；遇到其他值抛出 ValueError。
    """

    key: str
    """全局唯一标识，优先使用 manifest package 值。"""

    package: str
    """Python 包名，如 ``im.polaris.weather``。"""

    name: str
    """人类可读名称，如 ``天气应用``。"""

    version: str = "0.1.0"
    """App 版本号。"""

    directory: Path = Path()
    """App 目录路径。"""

    transport: str = "stdio"
    """传输方式。一期只支持 ``stdio``。"""

    command: list[str] = field(default_factory=list)
    """启动命令，如 ``["uv", "run", "python", "-m", "apps.aurora-app-diary.mcp_server"]``。"""

    args: list[str] = field(default_factory=list)
    """额外命令行参数。"""

    env: dict[str, str] = field(default_factory=dict)
    """环境变量。"""

    enabled: bool = True
    """是否启用。"""

    startup: dict[str, object] = field(default_factory=dict)
    """传递给本地 MCP Server 的启动参数。"""

    health_timeout_seconds: float = 10.0
    """健康检查超时秒数。"""

    def __post_init__(self) -> None:
        """验证约束。"""
        if self.transport != "stdio":
            msg = f"transport 只支持 'stdio'，收到 '{self.transport}'"
            raise ValueError(msg)

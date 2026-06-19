"""日记 MCP Server 入口测试。

测试 FastMCP 的工具注册和 tool 响应格式。
由于 App 目录名包含横线（``aurora-app-diary``），通过 ``MCPServerKit``
以脚本入口启动。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from src.platform.mcp_kit.client_manager import MCPClientManager
from src.platform.mcp_kit.server_kit import MCPServerKit
from src.platform.mcp_kit.server_spec import MCPServerSpec

pytestmark = pytest.mark.anyio

_PROJECT_ROOT = Path(__file__).resolve().parent.parent


class TestDiaryMcpTools:
    """验证 ``mcp_server.py`` 的工具注册。"""

    async def test_server_imports(self) -> None:
        """验证 mcp_server 模块可加载且工具已注册。"""
        mcp_path = _PROJECT_ROOT / "apps" / "aurora-app-diary" / "mcp_server.py"
        spec = importlib.util.spec_from_file_location("mcp_server_test", str(mcp_path))
        if spec is None or spec.loader is None:
            raise ImportError(f"Cannot load module from {mcp_path}")  # noqa: TRY003
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        mcp = getattr(module, "mcp", None)
        assert mcp is not None, "mcp_server.py 应导出 FastMCP 实例"

    async def test_tool_list_via_stdio(self) -> None:
        """通过实际 MCP client/server stdio 会话获取工具列表。"""
        app_dir = _PROJECT_ROOT / "apps" / "aurora-app-diary"
        spec = MCPServerSpec(
            key="im.polaris.diary",
            package="im.polaris.diary",
            name="日记",
            directory=app_dir,
            command=["uv", "run", "python", "mcp_server.py"],
        )
        server_kit = MCPServerKit()
        client_manager = MCPClientManager(server_kit)

        try:
            await server_kit.start_all([spec])
            await client_manager.connect_all()
            tools = client_manager.list_all_tools()["im.polaris.diary"]
            tool_names = {tool.name for tool in tools}

            assert {"write_diary", "read_diary", "list_dates"} <= tool_names
        finally:
            await client_manager.shutdown()
            await server_kit.stop_all()

"""日记 MCP Server 入口测试。

测试 FastMCP 的工具注册和 tool 响应格式。
由于 App 目录名包含横线（``aurora-app-diary``），使用 subprocess 直接运行脚本。
"""

from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path

import pytest

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
        """通过 stdio 启动 MCP Server，发送 tools/list 请求。"""
        server_script = str(_PROJECT_ROOT / "apps" / "aurora-app-diary" / "mcp_server.py")

        proc = await asyncio.create_subprocess_exec(
            "uv",
            "run",
            "python",
            server_script,
            cwd=str(_PROJECT_ROOT),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        # 发送初始化请求
        init_request = (
            '{"jsonrpc":"2.0","id":1,"method":"initialize",'
            '"params":{"protocolVersion":"2024-11-05",'
            '"capabilities":{},"clientInfo":{"name":"test","version":"0.1.0"}}}\n'
        )
        list_request = '{"jsonrpc":"2.0","id":2,"method":"tools/list"}\n'

        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(input=(init_request + list_request).encode()),
                timeout=15.0,
            )
        except TimeoutError:
            proc.kill()
            stdout, stderr = await proc.communicate()
            raise

        output = stdout.decode()
        err_output = stderr.decode()

        # FastMCP 在 initialize 后会自动发送 initialized notification，
        # 所以 tools/list 的响应应该在 stdio 中出现
        assert proc.returncode == 0, (
            f"Server exited with code {proc.returncode}\nstderr: {err_output[:500]}\nstdout: {output[:500]}"
        )
        assert '"write_diary"' in output, f"未找到 write_diary 工具\n输出: {output[:1000]}"
        assert '"read_diary"' in output
        assert '"list_dates"' in output

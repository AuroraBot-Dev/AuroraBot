"""MCP ServerKit + ClientManager 单元测试。"""

from __future__ import annotations

import asyncio

import pytest
from mcp.types import CallToolResult, TextContent

from src.platform.mcp.client_manager import ClientConnection, MCPClientManager
from src.platform.mcp.server_kit import MCPServerKit
from src.platform.mcp.server_spec import MCPServerSpec

pytestmark = pytest.mark.anyio


# ── MCPServerKit ──


class TestMCPServerKit:
    def test_empty_init(self) -> None:
        kit = MCPServerKit()
        assert kit.processes == {}

    def test_skips_disabled(self) -> None:
        kit = MCPServerKit()
        spec = MCPServerSpec(key="test", package="im.polaris.test", name="测试", enabled=False)

        async def run() -> None:
            await kit.start_all([spec])
            assert kit.processes == {}

        asyncio.run(run())

    def test_start_without_command_raises(self) -> None:
        kit = MCPServerKit()
        spec = MCPServerSpec(key="test", package="im.polaris.test", name="测试", enabled=True)

        async def run() -> None:
            with pytest.raises(RuntimeError, match="没有配置启动命令"):
                await kit.start_one(spec)

        asyncio.run(run())

    def test_start_nonexistent_command(self) -> None:
        kit = MCPServerKit()
        spec = MCPServerSpec(
            key="test",
            package="im.polaris.test",
            name="测试",
            enabled=True,
            command=["nonexistent_cmd_xyz"],
        )

        async def run() -> None:
            with pytest.raises(RuntimeError, match=r"启动.*失败"):
                await kit.start_one(spec)

        asyncio.run(run())

    def test_health_report_empty(self) -> None:
        kit = MCPServerKit()
        assert kit.health_report() == {}

    def test_stop_nonexistent(self) -> None:
        kit = MCPServerKit()

        async def run() -> None:
            await kit.stop_one("nonexistent")

        asyncio.run(run())


# ── MCPClientManager ──


class TestMCPClientManager:
    def test_empty_init(self) -> None:
        kit = MCPServerKit()

        mgr = MCPClientManager(kit)
        assert mgr.connections == {}

    def test_list_all_tools_empty(self) -> None:
        kit = MCPServerKit()

        mgr = MCPClientManager(kit)
        assert mgr.list_all_tools() == {}

    def test_tools_as_prompt_text_empty(self) -> None:
        kit = MCPServerKit()

        mgr = MCPClientManager(kit)
        text = mgr.tools_as_prompt_text()
        assert "暂无可用工具" in text

    def test_call_tool_no_prefix_raises(self) -> None:
        kit = MCPServerKit()
        from src.platform.mcp.client_manager import MCPToolCallError

        mgr = MCPClientManager(kit)

        async def run() -> None:
            with pytest.raises(MCPToolCallError, match="缺少前缀"):
                await mgr.call_tool("no_prefix")

        asyncio.run(run())

    def test_call_tool_no_connection(self) -> None:
        kit = MCPServerKit()
        from src.platform.mcp.client_manager import MCPToolCallError

        mgr = MCPClientManager(kit)

        async def run() -> None:
            with pytest.raises(MCPToolCallError, match="未找到 Server 连接"):
                await mgr.call_tool("im.polaris.test.echo")

        asyncio.run(run())

    def test_on_notification_register_and_unregister(self) -> None:
        kit = MCPServerKit()

        mgr = MCPClientManager(kit)
        called: list[tuple[str, dict[str, object]]] = []

        def handler(key: str, params: dict[str, object]) -> None:
            called.append((key, params))

        unregister = mgr.on_notification("aurora/event", handler)
        assert "aurora/event" in mgr._notification_handlers
        assert len(mgr._notification_handlers["aurora/event"]) == 1

        unregister()
        assert mgr._notification_handlers["aurora/event"] == []

    async def test_call_tool_returns_serializable_result(self) -> None:
        class FakeSession:
            async def call_tool(self, _name: str, _arguments: dict[str, object]) -> CallToolResult:
                return CallToolResult(content=[TextContent(type="text", text="ok")])

        kit = MCPServerKit()
        mgr = MCPClientManager(kit)
        mgr._connections["im.polaris.test"] = ClientConnection(
            server_key="im.polaris.test",
            session=FakeSession(),  # type: ignore[arg-type]
        )

        result = await mgr.call_tool("im.polaris.test.echo", {"message": "hello"})

        assert result["ok"] is True
        assert result["text"] == "ok"
        assert result["is_error"] is False
        assert result["content"] == [{"type": "text", "text": "ok", "annotations": None, "meta": None}]

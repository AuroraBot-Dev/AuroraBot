"""MCP 工具派发器测试。"""

from __future__ import annotations

import pytest

from src.brain.nodes.routers.mcp_tool_dispatcher import MCPToolDispatcher

pytestmark = pytest.mark.anyio


class _FakeClientManager:
    async def call_tool(self, _tool_name: str, _arguments: dict[str, object]) -> dict[str, object]:
        return {
            "ok": True,
            "text": "日记已写入",
            "is_error": False,
            "content": [{"type": "text", "text": "日记已写入"}],
            "structured_content": None,
        }


async def test_dispatcher_writes_completed_result_from_client_manager_dict() -> None:
    dispatcher = MCPToolDispatcher("dispatcher")
    dispatcher.client_manager = _FakeClientManager()  # type: ignore[assignment]

    update = await dispatcher._dispatch_action(
        {
            "tool": "im.polaris.diary.write_diary",
            "arguments": {"date": "2026-06-19", "content": "测试"},
        },
        "trace-1",
    )

    assert update is not None
    assert update.content["envelope"]["status"] == "completed"
    assert update.content["result"]["text"] == "日记已写入"

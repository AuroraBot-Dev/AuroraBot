"""MCP EventBridge + AMP 预处理单元测试。"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from src.brain.nodes.event_bridge import run_mcp_event_bridge
from src.brain.nodes.routers.message_preprocessor import MessagePreprocessor

# ── _extract_event_data ──


class TestExtractEventData:
    """测试 ``MessagePreprocessor._extract_event_data`` 的双格式兼容。"""

    def test_legacy_flat_format(self) -> None:
        data = {
            "type": "message.received",
            "session_id": "sess_1",
            "summary": "用户发言",
            "payload": {"user_id": "u1", "text": "hello", "is_group": True, "group_id": "g1"},
            "source": "im.polaris.qq",
            "id": "evt_001",
        }
        result = MessagePreprocessor._extract_event_data(data)
        assert result["type"] == "message.received"
        assert result["session_id"] == "sess_1"
        assert result["payload"]["user_id"] == "u1"

    def test_amp_envelope_format(self) -> None:
        data = {
            "header": {
                "method": "aurora/event",
                "message_id": "msg_abc",
                "source": {"app": "im.polaris.qq", "instance": "default"},
                "protocol": "amp/1.0",
                "timestamp": "2026-06-19T12:00:00+08:00",
            },
            "payload": {
                "type": "message.received",
                "session_id": "group_123",
                "summary": "用户发了消息",
                "data": {"user_id": "u2", "text": "hi", "is_group": True, "group_id": "g2"},
                "expire_at": None,
            },
        }
        result = MessagePreprocessor._extract_event_data(data)
        assert result["type"] == "message.received"
        assert result["session_id"] == "group_123"
        assert result["payload"]["user_id"] == "u2"
        assert result["message_id"] == "msg_abc"
        assert result["source"] == "im.polaris.qq"

    def test_amp_format_event_text(self) -> None:
        """AMP 格式能正确生成 message.received 文本。"""
        data = {
            "header": {"source": {"app": "im.polaris.qq"}},
            "payload": {
                "type": "message.received",
                "data": {"user_id": "u3", "text": "测试消息", "is_group": True, "group_id": "g3"},
            },
        }
        text = MessagePreprocessor._format_event_as_text(data)
        assert "u3" in text
        assert "g3" in text
        assert "测试消息" in text


# ── AMP format message preprocessor full flow ──


class FakeCircuit:
    """模拟 Circuit 用于测试。"""

    def __init__(self) -> None:
        self.updates: list[tuple[Any, str]] = []

    async def apply_update(self, update: Any, node_id: str) -> None:
        self.updates.append((update, node_id))


class FakeMcpClientManager:
    """模拟 MCPClientManager 用于测试。"""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[tuple[str, str, dict[str, object]]] = asyncio.Queue()

    @property
    def notification_queue(self) -> asyncio.Queue[tuple[str, str, dict[str, object]]]:
        return self._queue


class TestRunMcpEventBridge:
    """测试 ``run_mcp_event_bridge`` 的队列消费与文件写入。"""

    @pytest.mark.anyio
    async def test_receive_amp_event(self) -> None:
        client_mgr = FakeMcpClientManager()
        circuit = FakeCircuit()
        stop_event = asyncio.Event()

        # 启动 bridge （在后台运行）
        bridge_task = asyncio.create_task(
            run_mcp_event_bridge(client_mgr, circuit, stop_event)  # type: ignore[arg-type]
        )

        await asyncio.sleep(0.1)

        # 放入一个 AMP 事件
        await client_mgr._queue.put(
            (
                "im.polaris.test",
                "aurora/event",
                {
                    "header": {
                        "method": "aurora/event",
                        "message_id": "test-001",
                        "source": {"app": "im.polaris.test", "instance": "default"},
                        "protocol": "amp/1.0",
                        "timestamp": "2026-06-19T12:00:00+08:00",
                    },
                    "payload": {
                        "type": "diary.written",
                        "session_id": "s1",
                        "summary": "日记已写入",
                        "data": {"date": "2026-06-19"},
                        "expire_at": None,
                    },
                },
            )
        )

        await asyncio.sleep(0.2)

        # 停止 bridge
        stop_event.set()
        await bridge_task

        # 验证 circuit 收到了文件更新
        assert len(circuit.updates) >= 1
        update, node_id = circuit.updates[0]
        assert node_id == "mcp_event_bridge"
        assert "inbox/pending/event_diary_written_" in update.descriptor.path

        content = update.content
        assert content["header"]["method"] == "aurora/event"
        assert content["payload"]["type"] == "diary.written"

    @pytest.mark.anyio
    async def test_skip_non_event_notification(self) -> None:
        client_mgr = FakeMcpClientManager()
        circuit = FakeCircuit()
        stop_event = asyncio.Event()

        bridge_task = asyncio.create_task(
            run_mcp_event_bridge(client_mgr, circuit, stop_event)  # type: ignore[arg-type]
        )

        await asyncio.sleep(0.1)

        # 放入非 aurora/event 的通知（应跳过）
        await client_mgr._queue.put(
            (
                "im.polaris.test",
                "aurora/log",
                {"data": "log message"},
            )
        )

        await asyncio.sleep(0.2)
        assert len(circuit.updates) == 0

        stop_event.set()
        await bridge_task

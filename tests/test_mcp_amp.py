"""MCP 基础设施单元测试。"""

from __future__ import annotations

import uuid

import pytest

from src.platform.mcp_kit.amp import (
    amp_to_file_event,
    build_event_envelope,
    legacy_app_event_to_amp,
    parse_amp_envelope,
)
from src.platform.mcp_kit.server_spec import MCPServerSpec
from src.platform.mcp_kit.tool_schema import (
    mcp_tool_to_openai_tool,
    mcp_tools_to_prompt_text,
    normalize_tool_name,
    validate_tool_names_unique,
)

# ── MCPServerSpec ──


class TestMCPServerSpec:
    def test_minimal_spec(self) -> None:
        spec = MCPServerSpec(key="test", package="im.polaris.test", name="测试")
        assert spec.key == "test"
        assert spec.package == "im.polaris.test"
        assert spec.transport == "stdio"
        assert spec.enabled is True

    def test_transport_validation(self) -> None:
        with pytest.raises(ValueError, match=r"只支持.*stdio"):
            MCPServerSpec(key="t", package="p", name="t", transport="sse")

    def test_custom_values(self) -> None:
        spec = MCPServerSpec(
            key="diary",
            package="im.polaris.diary",
            name="日记",
            version="1.0.0",
            command=["uv", "run", "python", "mcp_server.py"],
            env={"DATA_DIR": "/tmp"},
            health_timeout_seconds=5.0,
        )
        assert spec.command == ["uv", "run", "python", "mcp_server.py"]
        assert spec.env == {"DATA_DIR": "/tmp"}
        assert spec.health_timeout_seconds == 5.0  # noqa: PLR2004


# ── AMP envelope ──


class TestAMPBuild:
    def test_build_minimal(self) -> None:
        envelope = build_event_envelope(
            source_app="im.polaris.test",
            event_type="test.event",
        )
        assert envelope.header.protocol == "amp/1.0"
        assert envelope.header.method == "aurora/event"
        assert envelope.header.source.app == "im.polaris.test"
        assert envelope.payload.type == "test.event"
        assert uuid.UUID(envelope.header.message_id)
        assert envelope.header.timestamp

    def test_build_full(self) -> None:
        envelope = build_event_envelope(
            source_app="im.polaris.qq",
            event_type="message.received",
            session_id="group_123",
            summary="用户发了消息",
            data={"user_id": "123", "text": "hello"},
            method="aurora/event",
            expire_at="2026-06-20T12:00:00+08:00",
        )
        assert envelope.payload.session_id == "group_123"
        assert envelope.payload.summary == "用户发了消息"
        assert envelope.payload.data == {"user_id": "123", "text": "hello"}
        assert envelope.payload.expire_at == "2026-06-20T12:00:00+08:00"

    def test_accepts_mcp_signal_method(self) -> None:
        envelope = build_event_envelope(
            source_app="test",
            event_type="capability.changed",
            method="mcp.notification",
        )
        assert envelope.header.method == "mcp.notification"

    def test_empty_method(self) -> None:
        with pytest.raises(ValueError, match="method 不能为空"):
            build_event_envelope(
                source_app="test",
                event_type="x",
                method="",
            )


class TestAMPParsing:
    def test_parse_valid_envelope(self) -> None:
        raw = {
            "header": {
                "protocol": "amp/1.0",
                "method": "aurora/event",
                "message_id": "abc-123",
                "timestamp": "2026-06-19T12:00:00+08:00",
                "source": {"app": "im.polaris.test", "instance": "default"},
            },
            "payload": {
                "type": "test.event",
                "session_id": "sess_1",
                "summary": "测试事件",
                "data": {"key": "value"},
                "expire_at": None,
            },
        }
        envelope = parse_amp_envelope(raw)
        assert envelope.header.message_id == "abc-123"
        assert envelope.payload.type == "test.event"
        assert envelope.payload.data == {"key": "value"}

    def test_parse_invalid_type(self) -> None:
        with pytest.raises(TypeError):
            parse_amp_envelope("not a dict")

    def test_parse_malformed(self) -> None:
        with pytest.raises((ValueError, TypeError)):
            parse_amp_envelope([1, 2, 3])

    def test_roundtrip(self) -> None:
        original = build_event_envelope(
            source_app="im.polaris.weather",
            event_type="weather.reported",
            data={"city": "北京", "temp": 22},
        )
        as_dict = amp_to_file_event(original)
        parsed = parse_amp_envelope(as_dict)
        assert parsed.header.message_id == original.header.message_id
        assert parsed.payload.type == "weather.reported"
        assert parsed.payload.data == {"city": "北京", "temp": 22}


class TestAMPConversion:
    def test_legacy_app_event_to_amp(self) -> None:
        class FakeAppEvent:
            def __init__(self) -> None:
                self.source = "im.polaris.test"
                self.type = "test.event"
                self.session_id = "sess_1"
                self.summary = "旧事件"
                self.data: dict[str, object] = {"old": True}

        event = FakeAppEvent()
        envelope = legacy_app_event_to_amp(event)
        assert envelope.header.source.app == "im.polaris.test"
        assert envelope.payload.type == "test.event"
        assert envelope.payload.data == {"old": True}


# ── Tool schema ──


class FakeTool:
    """Mimics MCP Tool for testing."""

    def __init__(self, name: str, description: str = "", input_schema: dict | None = None) -> None:
        self.name = name
        self.description = description
        self.inputSchema = input_schema or {"type": "object"}


class TestNormalizeToolName:
    def test_no_prefix(self) -> None:
        assert normalize_tool_name("im.polaris.test", "echo") == "im.polaris.test.echo"

    def test_already_has_prefix(self) -> None:
        assert normalize_tool_name("im.polaris.test", "im.polaris.test.echo") == "im.polaris.test.echo"


class TestMcpToolToOpenaiTool:
    def test_basic_conversion(self) -> None:
        tool = FakeTool("get_weather", "查询天气", {"type": "object", "properties": {"city": {"type": "string"}}})
        result = mcp_tool_to_openai_tool(tool, server_name="im.polaris.weather")
        assert result["type"] == "function"
        assert result["function"]["name"] == "im.polaris.weather.get_weather"
        assert "city" in result["function"]["parameters"]["properties"]


class TestMcpToolsToPromptText:
    def test_empty(self) -> None:
        assert mcp_tools_to_prompt_text([]) == "可用命令："

    def test_with_tools(self) -> None:
        tools = [
            FakeTool(
                "echo",
                "回显消息",
                {"type": "object", "properties": {"msg": {"type": "string", "description": "消息内容"}}},
            ),
        ]
        text = mcp_tools_to_prompt_text(tools, server_prefix="im.polaris.test")
        assert "im.polaris.test.echo" in text
        assert "回显消息" in text
        assert "msg" in text


class TestValidateToolNames:
    def test_no_conflict(self) -> None:
        tools = [FakeTool("a"), FakeTool("b")]
        result = validate_tool_names_unique(tools, server_name="im.polaris.test")
        assert len(result) == 2  # noqa: PLR2004

    def test_conflict(self) -> None:
        tools = [FakeTool("a"), FakeTool("a")]
        with pytest.raises(ValueError, match="工具名冲突"):
            validate_tool_names_unique(tools, server_name="im.polaris.test")

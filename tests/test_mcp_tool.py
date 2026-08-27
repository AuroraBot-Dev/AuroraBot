from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

import pytest

from src.contracts import ToolCall, ToolStatus
from src.mcp import (
    McpCallRejectedError,
    McpCallResult,
    McpCallUnknownError,
    McpContentBlock,
    McpRemoteTool,
    McpTool,
    McpToolsPage,
    bind_mcp_tool,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping
    from typing import Any

_TIMEOUT_SECONDS = 7.5


class FakeCallClient:
    def __init__(self, outcome: McpCallResult | Exception) -> None:
        self.outcome = outcome
        self._connected = True
        self.calls: list[tuple[str, Mapping[str, Any], float]] = []

    @property
    def protocol_version(self) -> str:
        return "2026-07-28"

    @property
    def connected(self) -> bool:
        return self._connected

    async def list_tools(self, *, cursor: str | None = None) -> McpToolsPage:
        raise AssertionError(f"冻结后的 Tool 不应重新发现目录：{cursor}")

    async def call_tool(
        self,
        name: str,
        arguments: Mapping[str, Any],
        timeout_seconds: float,
    ) -> McpCallResult:
        self.calls.append((name, dict(arguments), timeout_seconds))
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome

    async def bind_observers(
        self,
        *,
        catalog_changed: Callable[[], Awaitable[None]],
        disconnected: Callable[[str], Awaitable[None]],
    ) -> None:
        raise AssertionError(f"单 Tool 测试不绑定观察者：{catalog_changed!r} {disconnected!r}")

    def activate_events(self) -> None:
        raise AssertionError("单 Tool 测试不激活事件")

    def deactivate_events(self) -> None:
        return None

    async def close(self) -> None:
        self._connected = False


@dataclass(frozen=True, slots=True)
class _Expected:
    content: str
    status: ToolStatus


@pytest.mark.parametrize(
    ("outcome", "expected"),
    (
        (
            McpCallResult(False, {"z": 1, "a": "中文"}, (McpContentBlock("text", "ignored"),)),
            _Expected('{"a":"中文","z":1}', ToolStatus.SUCCEEDED),
        ),
        (
            McpCallResult(
                False,
                None,
                (
                    McpContentBlock("text", "第一段"),
                    McpContentBlock("text", "  "),
                    McpContentBlock("text", "第二段"),
                ),
            ),
            _Expected("第一段\n第二段", ToolStatus.SUCCEEDED),
        ),
        (
            McpCallResult(False, None, ()),
            _Expected("MCP 工具已完成，但未返回文本内容", ToolStatus.SUCCEEDED),
        ),
        (
            McpCallResult(True, None, (McpContentBlock("text", "远端拒绝"),)),
            _Expected("远端拒绝", ToolStatus.FAILED),
        ),
        (
            McpCallResult(True, None, (McpContentBlock("text", "效果无法确认"),), effect_unknown=True),
            _Expected("效果无法确认", ToolStatus.UNKNOWN),
        ),
        (
            McpCallResult(False, None, (McpContentBlock("image"),)),
            _Expected("MCP Tool 返回了当前 transcript 不支持的内容类型：image", ToolStatus.FAILED),
        ),
        (
            McpCallUnknownError("效果无法确认"),
            _Expected("效果无法确认", ToolStatus.UNKNOWN),
        ),
        (
            McpCallRejectedError("调用没有发送"),
            _Expected("调用没有发送", ToolStatus.FAILED),
        ),
        (
            RuntimeError("unexpected boundary failure"),
            _Expected("MCP 调用结果无法确认：RuntimeError: unexpected boundary failure", ToolStatus.UNKNOWN),
        ),
    ),
)
def test_mcp_tool_normalizes_structured_text_empty_error_nontext_and_uncertain_results(
    outcome: McpCallResult | Exception,
    expected: _Expected,
) -> None:
    client = FakeCallClient(outcome)
    binding = bind_mcp_tool(
        "org.example.tools",
        McpRemoteTool("echo", "回显", {"type": "object", "properties": {"value": {"type": "string"}}}),
    )
    tool = McpTool(binding, client, _TIMEOUT_SECONDS)

    result = asyncio.run(tool.execute(ToolCall("call-1", tool.definition.name, {"value": "你好"})))

    assert result.content == expected.content
    assert result.status is expected.status
    assert result.is_error is (expected.status is not ToolStatus.SUCCEEDED)
    assert client.calls == [("echo", {"value": "你好"}, _TIMEOUT_SECONDS)]


def test_mcp_tool_rejects_wrong_route_and_disconnected_client_without_sending() -> None:
    client = FakeCallClient(McpCallResult(False, None, ()))
    binding = bind_mcp_tool(
        "org.example.tools",
        McpRemoteTool("echo", "回显", {"type": "object"}),
    )
    tool = McpTool(binding, client, _TIMEOUT_SECONDS)

    wrong_route = asyncio.run(tool.execute(ToolCall("wrong", "aur.mcp.org.example.tools.other", {})))
    client._connected = False
    disconnected = asyncio.run(tool.execute(ToolCall("offline", tool.definition.name, {})))

    assert wrong_route.status is ToolStatus.FAILED and "路由不匹配" in wrong_route.content
    assert disconnected.status is ToolStatus.FAILED and "未连接" in disconnected.content
    assert client.calls == []


def test_bind_mcp_tool_rejects_invalid_name_and_non_object_schema_without_rewriting() -> None:
    with pytest.raises(ValueError, match="合法 Aurora 工具 ID"):
        bind_mcp_tool("org.example.tools", McpRemoteTool(" valid_name", None, {"type": "object"}))
    with pytest.raises(ValueError, match="合法 Aurora 工具 ID"):
        bind_mcp_tool("org.example.tools", McpRemoteTool("valid_name ", None, {"type": "object"}))
    with pytest.raises(ValueError, match="合法 Aurora 工具 ID"):
        bind_mcp_tool("Org.example.tools", McpRemoteTool("valid_name", None, {"type": "object"}))
    with pytest.raises(ValueError, match="input schema 必须是 object"):
        bind_mcp_tool("org.example.tools", McpRemoteTool("valid", None, {"type": "array"}))

    binding = bind_mcp_tool("org.example.tools", McpRemoteTool("valid_name", None, {"type": "object"}))
    assert binding.raw_name == "valid_name"
    assert binding.definition.name == "aur.mcp.org.example.tools.valid_name"
    assert binding.definition.description == "MCP 工具：valid_name"


def test_bind_mcp_tool_keeps_third_party_camelcase_raw_name_without_rewriting() -> None:
    binding = bind_mcp_tool(
        "com.github.windows_mcp",
        McpRemoteTool("Screenshot", "截取屏幕", {"type": "object", "properties": {}}),
    )

    assert binding.raw_name == "Screenshot"
    assert binding.definition.name == "aur.mcp.com.github.windows_mcp.Screenshot"
    assert binding.definition.description == "截取屏幕"

    mixed = bind_mcp_tool("com.github.windows_mcp", McpRemoteTool("WaitFor", None, {"type": "object"}))
    assert mixed.raw_name == "WaitFor"
    assert mixed.definition.name == "aur.mcp.com.github.windows_mcp.WaitFor"


def test_mcp_remote_tool_and_definition_deep_freeze_nested_json() -> None:
    schema = {
        "type": "object",
        "properties": {
            "mode": {"type": "string", "enum": ["one", "two"]},
        },
    }
    metadata = {"observe": ["qq:mode:{mode}"]}
    remote = McpRemoteTool("choose", "选择", schema, metadata)
    binding = bind_mcp_tool("org.example.tools", remote)

    schema["properties"]["mode"]["enum"].append("mutated")
    metadata["observe"].append("mutated")

    remote_mode = remote.input_schema["properties"]["mode"]
    definition_mode = binding.definition.parameters["properties"]["mode"]
    assert remote_mode["enum"] == ("one", "two")
    assert definition_mode["enum"] == ("one", "two")
    assert remote.tool_contract == {"observe": ("qq:mode:{mode}",)}
    with pytest.raises(TypeError):
        remote_mode["type"] = "integer"
    with pytest.raises(TypeError):
        cast("dict[str, object]", binding.definition.parameters)["new"] = True


def test_scope_contract_defaults_to_app_scope_and_resolves_negotiated_templates() -> None:
    default_binding = bind_mcp_tool(
        "org.example.tools",
        McpRemoteTool("status", "状态", {"type": "object", "properties": {}}),
    )
    default_tool = McpTool(default_binding, FakeCallClient(McpCallResult(False, None, ())), _TIMEOUT_SECONDS)
    default_scopes = default_tool.resolve_scopes(ToolCall("default", default_tool.definition.name, {}))
    assert default_scopes.observe == frozenset({"aurora:mcp:org.example.tools"})
    assert default_scopes.publish == frozenset({"aurora:mcp:org.example.tools"})

    binding = bind_mcp_tool(
        "org.example.tools",
        McpRemoteTool(
            "send",
            "发送",
            {
                "type": "object",
                "properties": {
                    "group_id": {"type": "integer"},
                    "user_id": {"type": "string"},
                },
            },
            {
                "observe": ["qq:group:{group_id}", "qq:private:{user_id}"],
                "publish": ["qq:group:{group_id}"],
            },
        ),
    )
    tool = McpTool(binding, FakeCallClient(McpCallResult(False, None, ())), _TIMEOUT_SECONDS)
    scopes = tool.resolve_scopes(ToolCall("scoped", tool.definition.name, {"group_id": 10001, "user_id": "20002"}))

    assert scopes.observe == frozenset({"qq:group:10001", "qq:private:20002"})
    assert scopes.publish == frozenset({"qq:group:10001"})


@pytest.mark.parametrize(
    ("metadata", "message"),
    (
        ([], "必须是对象"),
        ({"unknown": []}, "未知字段"),
        ({"observe": []}, "非空文本数组"),
        ({"observe": ["qq:{group_id}", "qq:{group_id}"]}, "重复模板"),
        ({"observe": ["qq:{missing}"]}, "未知顶层参数"),
        ({"observe": ["qq:{group.id}"]}, "语法非法"),
        ({"observe": [" qq:fixed"]}, "scope 非法"),
    ),
)
def test_scope_contract_rejects_malformed_metadata_during_discovery(metadata: object, message: str) -> None:
    remote = McpRemoteTool(
        "send",
        "发送",
        {"type": "object", "properties": {"group_id": {"type": "integer"}}},
        metadata,
    )

    with pytest.raises(ValueError, match=message):
        bind_mcp_tool("org.example.tools", remote)


@pytest.mark.parametrize(
    "arguments",
    (
        {},
        {"group_id": True},
        {"group_id": {"nested": 1}},
        {"group_id": "line\nbreak"},
    ),
)
def test_invalid_scope_argument_fails_before_any_remote_send(arguments: dict[str, object]) -> None:
    client = FakeCallClient(McpCallResult(False, None, ()))
    binding = bind_mcp_tool(
        "org.example.tools",
        McpRemoteTool(
            "send",
            "发送",
            {"type": "object", "properties": {"group_id": {"type": "integer"}}},
            {"observe": ["qq:group:{group_id}"], "publish": ["qq:group:{group_id}"]},
        ),
    )
    tool = McpTool(binding, client, _TIMEOUT_SECONDS)

    result = asyncio.run(tool.execute(ToolCall("invalid-scope", tool.definition.name, arguments)))

    assert result.status is ToolStatus.FAILED
    assert "scope 解析失败" in result.content
    assert client.calls == []

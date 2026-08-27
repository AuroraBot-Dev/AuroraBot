"""把冻结的 MCP 工具定义适配为 Aurora Tool。"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

from src.contracts import ToolCall, ToolDefinition, ToolOutput, ToolScopes, ToolStatus, mcp_scope
from src.mcp.models import McpCallRejectedError, McpCallResult, McpCallUnknownError, McpRemoteTool
from src.mcp.scopes import render_scope_template, validate_scope_template
from src.utils import get_logger

_logger = get_logger(__name__)

if TYPE_CHECKING:
    from src.mcp.client import McpClientPort

_TOOL_ID = re.compile(r"aur(?:\.[a-z][a-z0-9_-]*){2,}")


@dataclass(frozen=True, slots=True)
class McpToolBinding:
    """领域 Tool ID 与远端 package/raw-name 的冻结映射。"""

    package: str
    raw_name: str
    definition: ToolDefinition
    observe_templates: tuple[str, ...]
    publish_templates: tuple[str, ...]


def bind_mcp_tool(package: str, remote: McpRemoteTool) -> McpToolBinding:
    """校验一次发现项并形成稳定、不静默改名的领域定义。"""
    raw_name = remote.name
    tool_id = f"aur.mcp.{package}.{raw_name}"
    if not raw_name or raw_name != raw_name.strip() or _TOOL_ID.fullmatch(tool_id) is None:
        raise ValueError(f"MCP Tool 名称不能组成合法小写 Aurora ID：{package}/{remote.name}")
    if remote.input_schema.get("type") != "object":
        raise ValueError(f"MCP Tool input schema 必须是 object：{tool_id}")
    observe, publish = _scope_templates(package, remote)
    description = (remote.description or "").strip() or f"MCP 工具：{raw_name}"
    return McpToolBinding(
        package,
        raw_name,
        ToolDefinition(tool_id, description, remote.input_schema),
        observe,
        publish,
    )


class McpTool:
    """一个冻结 definition 与活连接之间的统一 Tool 适配器。"""

    def __init__(self, binding: McpToolBinding, client: McpClientPort, timeout_seconds: float) -> None:
        self._binding = binding
        self._client = client
        self._timeout_seconds = timeout_seconds

    @property
    def definition(self) -> ToolDefinition:
        return self._binding.definition

    def resolve_scopes(self, call: ToolCall) -> ToolScopes:
        """把协商后的模板解析为普通 engine scope 屏障。"""
        if call.name != self.definition.name:
            raise ValueError(f"MCP Tool 路由不匹配：{call.name}")
        return ToolScopes(
            frozenset(render_scope_template(item, call.arguments) for item in self._binding.observe_templates),
            frozenset(render_scope_template(item, call.arguments) for item in self._binding.publish_templates),
        )

    async def execute(self, call: ToolCall) -> ToolOutput:
        preflight = self._preflight(call)
        if preflight is not None:
            _logger.warning("MCP Tool 预检失败 tool=%s call_id=%s", call.name, call.call_id)
            return preflight
        if not self._client.connected:
            _logger.warning("MCP Tool 未发送 tool=%s call_id=%s reason=disconnected", call.name, call.call_id)
            return ToolOutput("MCP App 当前未连接，调用未发送", status=ToolStatus.FAILED)
        try:
            result = await self._client.call_tool(
                self._binding.raw_name,
                call.arguments,
                self._timeout_seconds,
            )
        except asyncio.CancelledError:
            raise
        except McpCallRejectedError as error:
            _logger.warning("MCP Tool 被拒绝 tool=%s call_id=%s", call.name, call.call_id)
            return ToolOutput(str(error), status=ToolStatus.FAILED)
        except McpCallUnknownError as error:
            _logger.warning("MCP Tool 效果未知 tool=%s call_id=%s", call.name, call.call_id)
            return ToolOutput(str(error), status=ToolStatus.UNKNOWN)
        except Exception as error:  # noqa: BLE001 - alternate client boundary must preserve unknown effects
            _logger.error(
                "MCP Tool 调用失败 tool=%s call_id=%s error_type=%s",
                call.name,
                call.call_id,
                type(error).__name__,
            )
            return ToolOutput(
                f"MCP 调用结果无法确认：{type(error).__name__}: {error}",
                status=ToolStatus.UNKNOWN,
            )
        output = _normalize_result(result)
        _logger.debug("MCP Tool 完成 tool=%s call_id=%s status=%s", call.name, call.call_id, output.status.value)
        return output

    def _preflight(self, call: ToolCall) -> ToolOutput | None:
        if call.name != self.definition.name:
            return ToolOutput(f"MCP Tool 路由不匹配：{call.name}", status=ToolStatus.FAILED)
        try:
            self.resolve_scopes(call)
        except ValueError as error:
            return ToolOutput(f"MCP Tool scope 解析失败：{error}", status=ToolStatus.FAILED)
        return None


def _normalize_result(result: McpCallResult) -> ToolOutput:
    if result.effect_unknown:
        return ToolOutput(_error_content(result), status=ToolStatus.UNKNOWN)
    if result.is_error:
        return ToolOutput(_error_content(result), status=ToolStatus.FAILED)
    unsupported = sorted({block.kind for block in result.content if block.kind != "text"})
    if unsupported:
        kinds = "、".join(unsupported)
        return ToolOutput(f"MCP Tool 返回了当前 transcript 不支持的内容类型：{kinds}", status=ToolStatus.FAILED)
    if result.structured_content is not None:
        try:
            content = json.dumps(
                result.structured_content,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        except (TypeError, ValueError) as error:
            return ToolOutput(f"MCP structuredContent 无法序列化：{error}", status=ToolStatus.FAILED)
        return ToolOutput(content)
    text = "\n".join(block.text for block in result.content if block.text is not None and block.text.strip())
    return ToolOutput(text or "MCP 工具已完成，但未返回文本内容")


def _error_content(result: McpCallResult) -> str:
    text = "\n".join(block.text for block in result.content if block.kind == "text" and block.text)
    if text.strip():
        return text
    if result.structured_content is not None:
        try:
            return json.dumps(result.structured_content, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        except (TypeError, ValueError):
            pass
    return "MCP Server 返回 isError"


def _scope_templates(package: str, remote: McpRemoteTool) -> tuple[tuple[str, ...], tuple[str, ...]]:
    default = (mcp_scope(package),)
    metadata = remote.tool_contract
    if metadata is None:
        return default, default
    if not isinstance(metadata, Mapping):
        raise ValueError("MCP Tool contract 元数据必须是对象")
    unexpected = set(metadata) - {"observe", "publish"}
    if unexpected:
        raise ValueError(f"MCP Tool contract 元数据包含未知字段：{sorted(unexpected)}")
    properties = remote.input_schema.get("properties", {})
    if not isinstance(properties, Mapping):
        raise ValueError("MCP Tool input schema properties 必须是对象")
    return (
        _template_direction(metadata, "observe", default, properties),
        _template_direction(metadata, "publish", default, properties),
    )


def _template_direction(
    metadata: Mapping[str, object],
    direction: str,
    default: tuple[str, ...],
    properties: Mapping[str, object],
) -> tuple[str, ...]:
    if direction not in metadata:
        return default
    raw = metadata[direction]
    if not isinstance(raw, (list, tuple)) or not raw or any(not isinstance(item, str) for item in raw):
        raise ValueError(f"MCP Tool contract {direction} 必须是非空文本数组")
    templates = tuple(raw)
    if len(templates) != len(set(templates)):
        raise ValueError(f"MCP Tool contract {direction} 不能包含重复模板")
    return tuple(validate_scope_template(item, properties) for item in templates)


__all__ = ["McpTool", "McpToolBinding", "bind_mcp_tool"]

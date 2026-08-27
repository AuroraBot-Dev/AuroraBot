"""工具定义、执行结果与效果端口契约。"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Protocol, cast

if TYPE_CHECKING:
    from src.contracts.model import ToolCall
    from src.contracts.world import ToolScopes

_AUR_TOOL_ID = re.compile(r"aur(?:\.[a-z][a-z0-9_-]*){2,}")
_MCP_TOOL_ID = re.compile(r"aur\.mcp\.[a-z][a-z0-9_-]*(?:\.[a-z][a-z0-9_-]*)*\.[A-Za-z][A-Za-z0-9_-]*")


def is_valid_tool_id(name: str) -> bool:
    """框架命名保持小写；MCP raw name 段属于第三方外部事实，允许大写风格。"""
    return _AUR_TOOL_ID.fullmatch(name) is not None or _MCP_TOOL_ID.fullmatch(name) is not None


def is_valid_mcp_tool_id(name: str) -> bool:
    """校验 ``aur.mcp.<package>.<raw_name>``：package 段小写，raw name 段允许大写。"""
    return _MCP_TOOL_ID.fullmatch(name) is not None


class ToolStatus(StrEnum):
    """一次工具调用的确定性结果状态。"""

    SUCCEEDED = "succeeded"
    FAILED = "failed"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    """模型可见的工具定义。"""

    name: str
    description: str
    parameters: Mapping[str, Any]

    def __post_init__(self) -> None:
        if not self.name or not self.description:
            raise ValueError("ToolDefinition requires name and description")
        frozen = _freeze_json(self.parameters)
        object.__setattr__(self, "parameters", cast("Mapping[str, Any]", frozen))


@dataclass(frozen=True, slots=True)
class ToolOutput:
    """工具调用的一次规范化文本结果。"""

    content: str
    status: ToolStatus = ToolStatus.SUCCEEDED

    def __post_init__(self) -> None:
        if not self.content.strip():
            raise ValueError("ToolOutput content must not be empty")
        if not isinstance(self.status, ToolStatus):
            raise TypeError("ToolOutput status must be a ToolStatus")

    @property
    def is_error(self) -> bool:
        """failed 与 unknown 都作为可供模型处理的错误消息。"""
        return self.status is not ToolStatus.SUCCEEDED


@dataclass(frozen=True, slots=True)
class DelegationRequest:
    """工具请求 engine 创建一个 child Agent。"""

    agent: str
    instruction: str

    def __post_init__(self) -> None:
        if not self.agent.strip() or not self.instruction.strip():
            raise ValueError("DelegationRequest requires agent and instruction")


type ToolResult = ToolOutput | DelegationRequest


class Tool(Protocol):
    """工具域中可注册、可路由的统一效果端口。"""

    @property
    def definition(self) -> ToolDefinition: ...

    async def execute(self, call: ToolCall) -> ToolResult: ...


class ScopedTool(Tool, Protocol):
    """可声明观察、发布世界域的可选 Tool 扩展契约。"""

    def resolve_scopes(self, call: ToolCall) -> ToolScopes: ...


def _freeze_json(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze_json(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item) for item in value)
    return value

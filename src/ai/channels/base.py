"""通道基础：RoleHandler 通道契约与共享工具序列化（RFC 0212）。"""

from __future__ import annotations

import hashlib
import json
import re
from abc import ABC, abstractmethod
from enum import StrEnum
from typing import TYPE_CHECKING, Any, ClassVar

from src.contracts import ModelCapabilityError, ModelResult, ToolDefinition

if TYPE_CHECKING:
    from src.ai.gateway import ModelGatewayService
    from src.contracts.configuration import ModelRoleConfig
    from src.contracts.model import ModelRequest


class RoleHandler(ABC):
    """通道契约：``endpoint``（通道）由实现声明，模型绑定由配置决定。"""

    endpoint: ClassVar[str]

    @abstractmethod
    async def complete(
        self,
        gateway: "ModelGatewayService",
        request: "ModelRequest",
        role: "ModelRoleConfig",
        negotiated: frozenset[str],
    ) -> ModelResult:
        """执行一次模型调用并返回规范化结果。"""


class _Msg(StrEnum):
    """本文件内所有用户或模型可见的硬编码文本。"""

    ALIAS_COLLISION = "tool alias collision"
    INVALID_ARGUMENTS = "tool arguments were not valid JSON"
    ARGUMENTS_NOT_OBJECT = "tool arguments were not an object"


_PROVIDER_TOOL_NAME_LIMIT = 64
_INVALID_TOOL_NAME = re.compile(r"[^A-Za-z0-9_-]+")

# ═══════════════════════════════════════════════════════════
# 共享工具序列化（原 _parsing 公共部分）
# ═══════════════════════════════════════════════════════════


def provider_tools(
    tools: tuple[ToolDefinition, ...], *, responses: bool
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    definitions: list[dict[str, Any]] = []
    aliases: dict[str, str] = {}
    for tool in tools:
        alias = _provider_tool_alias(tool.name)
        if alias in aliases:
            raise ModelCapabilityError(_Msg.ALIAS_COLLISION)
        aliases[alias] = tool.name
        aliases.setdefault(tool.name, tool.name)
        if responses:
            definitions.append(
                {
                    "type": "function",
                    "name": alias,
                    "description": tool.description,
                    "parameters": tool.parameters_schema,
                }
            )
        else:
            definitions.append(
                {
                    "type": "function",
                    "function": {"name": alias, "description": tool.description, "parameters": tool.parameters_schema},
                }
            )
    return definitions, aliases


def _provider_tool_alias(name: str) -> str:
    """生成 Provider 可接受且可由模型稳定复述的 Tool 名称。"""
    readable = _INVALID_TOOL_NAME.sub("_", name).strip("_")
    if not readable:
        readable = "tool"
    if readable[0].isdigit():
        readable = f"tool_{readable}"
    if len(readable) <= _PROVIDER_TOOL_NAME_LIMIT:
        return readable
    digest = hashlib.sha256(name.encode()).hexdigest()[:12]
    prefix = readable[: _PROVIDER_TOOL_NAME_LIMIT - len(digest) - 1].rstrip("_")
    return f"{prefix}_{digest}"


def parse_arguments(value: object, diagnostics: list[str]) -> dict[str, Any]:
    try:
        parsed = json.loads(value) if isinstance(value, str) else value
    except json.JSONDecodeError:
        diagnostics.append(_Msg.INVALID_ARGUMENTS)
        return {}
    if not isinstance(parsed, dict):
        diagnostics.append(_Msg.ARGUMENTS_NOT_OBJECT)
        return {}
    return parsed


def json_item(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump(mode="json")
        return dict(dumped) if isinstance(dumped, dict) else {"value": dumped}
    return {"type": str(getattr(value, "type", "unknown"))}

"""MCP 业务域与模板校验。

扩展以自己的命名空间拥有世界域，域声明模式允许发现前尚未知晓的扩展包名。
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from src.contracts.identity import WORLD_SCOPE_PATTERN, WORLD_SUB_SCOPE_PATTERN, world_scope

if TYPE_CHECKING:
    from collections.abc import Mapping

_PLACEHOLDER = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
_MAX_SCOPE_LENGTH = 256
_CONTROL_CHARACTER_LIMIT = 32

SCOPE_PATTERN = WORLD_SCOPE_PATTERN
SUB_SCOPE_PATTERN = WORLD_SUB_SCOPE_PATTERN


def mcp_scope(package: str) -> str:
    """返回一个 MCP App 拥有的世界域：``<package>:world``。"""
    return world_scope(package)


def owned_scope_prefix(package: str) -> str:
    """返回一个 MCP App 拥有的域前缀；扩展只能在自己名下声明域。"""
    return mcp_scope(package)


def owns_scope(package: str, scope: str) -> bool:
    """判断一个域是否落在该 App 自己的命名空间下。

    前缀必须整体成段匹配，避免 ``org.aurora.qq`` 误认领 ``org.aurora.qqq``；
    子域用 ``/`` 继续细分（``<package>:world/room/1``）。
    """
    prefix = owned_scope_prefix(package)
    return scope == prefix or scope.startswith(f"{prefix}/")


def validate_mcp_scope(scope: str) -> str:
    """校验并原样返回可进入 World frontier 的 MCP scope。"""
    if (
        not isinstance(scope, str)
        or not scope
        or scope != scope.strip()
        or len(scope) > _MAX_SCOPE_LENGTH
        or any(ord(char) < _CONTROL_CHARACTER_LIMIT for char in scope)
    ):
        raise ValueError("MCP scope 非法")
    return scope


def validate_scope_template(template: str, properties: Mapping[str, Any]) -> str:
    """发现时校验只引用顶层参数的 scope 模板。"""
    if not isinstance(template, str) or not template:
        raise ValueError("MCP scope 模板必须是非空文本")
    cursor = 0
    placeholders = 0
    for match in _PLACEHOLDER.finditer(template):
        if "{" in template[cursor : match.start()] or "}" in template[cursor : match.start()]:
            raise ValueError(f"MCP scope 模板语法非法：{template}")
        name = match.group(1)
        if name not in properties:
            raise ValueError(f"MCP scope 模板引用了未知顶层参数：{name}")
        cursor = match.end()
        placeholders += 1
    if "{" in template[cursor:] or "}" in template[cursor:]:
        raise ValueError(f"MCP scope 模板语法非法：{template}")
    if placeholders == 0:
        validate_mcp_scope(template)
    return template


def render_scope_template(template: str, arguments: Mapping[str, Any]) -> str:
    """只进行一次顶层文本/整数替换，并校验最终 scope。"""
    pieces: list[str] = []
    cursor = 0
    for match in _PLACEHOLDER.finditer(template):
        pieces.append(template[cursor : match.start()])
        name = match.group(1)
        if name not in arguments:
            raise ValueError(f"MCP scope 参数缺失：{name}")
        value = arguments[name]
        if isinstance(value, bool) or not isinstance(value, (str, int)):
            raise ValueError(f"MCP scope 参数必须是文本或整数：{name}")
        if isinstance(value, str) and not value:
            raise ValueError(f"MCP scope 参数不能为空：{name}")
        pieces.append(str(value))
        cursor = match.end()
    pieces.append(template[cursor:])
    return validate_mcp_scope("".join(pieces))


__all__ = [
    "mcp_scope",
    "owned_scope_prefix",
    "owns_scope",
    "render_scope_template",
    "validate_mcp_scope",
    "validate_scope_template",
]

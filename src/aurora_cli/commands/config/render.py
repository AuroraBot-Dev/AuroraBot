"""把实例化后的配置 DTO 渲染成 Python dataclass 风格文本。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from collections.abc import Sequence

_INDENT = "    "
_INLINE_WIDTH = 88


def render_value(value: object, level: int = 0) -> str:
    """递归渲染任意配置值；短容器保持单行，长容器按层缩进。"""
    if is_dataclass(value) and not isinstance(value, type):
        return _render_dataclass(value, level)
    if isinstance(value, Enum):
        return f"{type(value).__name__}.{value.name}"
    if isinstance(value, Mapping):
        rendered = [f"{render_value(key, level + 1)}: {render_value(item, level + 1)}" for key, item in value.items()]
        return _render_container(rendered, "{", "}", level)
    if isinstance(value, (tuple, list)):
        rendered = [render_value(item, level + 1) for item in value]
        return _render_container(rendered, "(", ")", level, single_comma=True)
    if isinstance(value, (frozenset, set)):
        rendered = [render_value(item, level + 1) for item in sorted(value, key=repr)]
        inner = _render_container(rendered, "{", "}", level)
        return f"frozenset({inner})"
    return repr(value)


def _render_dataclass(value: object, level: int) -> str:
    name = type(value).__name__
    members = fields(cast("Any", value))
    if not members:
        return f"{name}()"
    body = ",\n".join(
        f"{_INDENT * (level + 1)}{member.name}={render_value(getattr(value, member.name), level + 1)}"
        for member in members
    )
    return f"{name}(\n{body},\n{_INDENT * level})"


def _render_container(
    rendered: Sequence[str],
    opening: str,
    closing: str,
    level: int,
    *,
    single_comma: bool = False,
) -> str:
    if not rendered:
        return f"{opening}{closing}"
    inline = ", ".join(rendered)
    if single_comma and len(rendered) == 1:
        inline += ","
    candidate = f"{opening}{inline}{closing}"
    if all("\n" not in item for item in rendered) and len(candidate) <= _INLINE_WIDTH:
        return candidate
    body = ",\n".join(f"{_INDENT * (level + 1)}{item}" for item in rendered)
    return f"{opening}\n{body},\n{_INDENT * level}{closing}"

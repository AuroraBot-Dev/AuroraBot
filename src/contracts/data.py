"""协议数据的递归不可变边界。"""

from __future__ import annotations

import math
from collections.abc import Mapping
from types import MappingProxyType
from typing import Any


def freeze_object(data: Mapping[str, Any]) -> Mapping[str, Any]:
    """复制并冻结 JSON 对象，拒绝无法稳定传输的值。"""
    return MappingProxyType({key: _freeze_field(key, value) for key, value in data.items()})


def _freeze_field(key: object, value: object) -> object:
    """验证字段名并固定嵌套内容。"""
    if not isinstance(key, str):
        raise TypeError("协议对象的字段名必须是字符串")
    return _freeze_value(value)


def _freeze_value(value: object) -> object:
    """只接纳 JSON 能无歧义表达的标量与容器。"""
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("协议数据不能包含非有限数值")
        return value
    if isinstance(value, Mapping):
        return freeze_object(value)
    if isinstance(value, (tuple, list)):
        return tuple(_freeze_value(item) for item in value)
    raise TypeError(f"协议数据包含不支持的类型：{type(value).__name__}")

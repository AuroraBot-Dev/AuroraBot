"""独立执行契约使用的不可变 JSON 值。"""

from __future__ import annotations

import math
from collections.abc import Mapping
from types import MappingProxyType
from typing import Any


def freeze_object(value: Mapping[str, Any]) -> Mapping[str, Any]:
    result = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise TypeError("JSON 对象的键必须是字符串")
        result[key] = _freeze(item)
    return MappingProxyType(result)


def _freeze(value: object) -> object:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    if isinstance(value, Mapping):
        return freeze_object(value)
    if isinstance(value, (tuple, list)):
        return tuple(_freeze(item) for item in value)
    raise TypeError("协议数据必须是有限的 JSON 值")


def mutable_json(value: Any) -> Any:
    """在 schema 校验或 Provider 编码边界还原普通 JSON 容器。"""
    if isinstance(value, Mapping):
        return {key: mutable_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [mutable_json(item) for item in value]
    return value

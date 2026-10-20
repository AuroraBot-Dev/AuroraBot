"""LLM 输出的容错 JSON 提取工具。"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from types import MappingProxyType
from typing import Any, cast, overload


def freeze_json(value: object) -> object:
    """递归冻结 JSON 形状，避免值对象通过嵌套容器被改写。"""
    if isinstance(value, Mapping):
        return MappingProxyType({key: freeze_json(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(freeze_json(item) for item in value)
    return value


@overload
def thaw_json(value: Mapping[str, Any]) -> dict[str, Any]: ...


@overload
def thaw_json(value: object) -> object: ...


def thaw_json(value: object) -> object:
    """把冻结的 JSON 形状还原为 provider/序列化器可接受的容器。"""
    if isinstance(value, Mapping):
        return {key: thaw_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [thaw_json(item) for item in value]
    return value


def extract_json_from_text(raw: str) -> dict[str, object] | None:
    """移除代码围栏并提取 JSON 对象，允许修复未转义的控制字符，失败返回空值。"""
    if not raw or not raw.strip():
        return None
    text = raw.strip()

    text = re.sub(r"```json\s*|```\s*", "", text)

    try:
        result = json.loads(text)
        if isinstance(result, dict):
            return cast("dict[str, object]", result)
    except json.JSONDecodeError:
        pass

    try:
        result = _safe_parse_json_object(text)
        if isinstance(result, dict):
            return cast("dict[str, object]", result)
    except ValueError:
        pass

    fixed = _fix_json_multiline(text)
    if fixed != text:
        return extract_json_from_text(fixed)

    return None


def _fix_json_multiline(text: str) -> str:
    """替换 JSON 字符串值中未被转义的换行。"""
    result: list[str] = []
    in_string = False
    escape = False
    for ch in text:
        if in_string:
            if escape:
                result.append(ch)
                escape = False
                continue
            if ch == "\\":
                result.append(ch)
                escape = True
                continue
            if ch == "\n":
                result.append("\\n")
                continue
            if ch == "\r":
                result.append("\\r")
                continue
            if ch == "\t":
                result.append("\\t")
                continue
            if ch == '"':
                in_string = False
            result.append(ch)
        else:
            if ch == '"':
                in_string = True
            result.append(ch)
    return "".join(result)


def _safe_parse_json_object(content: str) -> object:
    """截取首个左花括号与最后一个右花括号之间的 JSON，格式错误时拒绝解析。"""
    left = content.find("{")
    right = content.rfind("}")
    if left == -1 or right == -1 or right <= left:
        raise ValueError("文本中没有完整的 JSON 对象")
    return json.loads(content[left : right + 1])

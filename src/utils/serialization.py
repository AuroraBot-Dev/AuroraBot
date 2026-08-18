"""LLM 输出的容错 JSON 提取工具。"""

from __future__ import annotations

import json
import re
from enum import StrEnum
from typing import cast


class _Msg(StrEnum):
    INVALID_JSON_OBJECT = "Invalid JSON object format"


def extract_json_from_text(raw: str) -> dict[str, object] | None:
    """从文本中提取 JSON 对象。

    均失败返回 None。
    """
    if not raw or not raw.strip():
        return None
    text = raw.strip()

    # 移除可能的 "```json" 和 "```"
    text = re.sub(r"```json\s*|```\s*", "", text)

    # 尝试解析 JSON 字符串
    try:
        result = json.loads(text)
        if isinstance(result, dict):
            return cast("dict[str, object]", result)
    except json.JSONDecodeError:
        pass

    # 尝试匹配首尾花括号
    try:
        result = _safe_parse_json_object(text)
        if isinstance(result, dict):
            return cast("dict[str, object]", result)
    except ValueError:
        pass

    # 尝试转义换行后重试
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
    """从文本中提取首个完整 JSON 对象

    找不到时抛出 ValueError
    """
    left = content.find("{")
    right = content.rfind("}")
    if left == -1 or right == -1 or right <= left:
        raise ValueError(_Msg.INVALID_JSON_OBJECT)
    return json.loads(content[left : right + 1])

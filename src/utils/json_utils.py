"""LLM 输出的 JSON 解析工具。

提供高容错的 JSON 提取方法，应对 LLM 在 JSON 前后附
带说明文字、markdown 代码块等非标准输出。
"""

from __future__ import annotations

import json
import re
from typing import Any


def parse_llm_json(raw: str) -> dict[str, Any] | None:
    """从 LLM 原始输出中提取 JSON 对象。

    依次尝试：
    1. 直接 JSON 解析
    2. ```json ... ``` 代码块提取
    3. 首尾花括号匹配
    均失败返回 None。
    """
    if not raw or not raw.strip():
        return None
    text = raw.strip()

    # 1) 直接解析
    try:
        result = json.loads(text)
        if isinstance(result, dict):
            return result
    except json.JSONDecodeError:
        pass

    # 2) ```json ... ``` 代码块
    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    if match:
        try:
            result = json.loads(match.group(1))
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass

    # 3) 首尾花括号
    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        try:
            result = json.loads(match.group(0))
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass

    # 4) 换行修复：LLM 经常在 JSON 字符串值里插入真正的换行 → 转义后重试
    fixed = _fix_json_multiline(text)
    if fixed != text:
        return parse_llm_json(fixed)

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


def safe_parse_json_object(content: str) -> dict[str, Any]:
    """从文本中提取首个完整 JSON 对象（花括号包裹）。

    与 ``parse_llm_json`` 不同，本函数在找不到 JSON 时直接
    抛出 ``ValueError`` 而非返回 None，适用于必须有结果的场景。
    """
    left = content.find("{")
    right = content.rfind("}")
    if left == -1 or right == -1 or right <= left:
        raise ValueError("LLM did not return a JSON object")
    return json.loads(content[left : right + 1])

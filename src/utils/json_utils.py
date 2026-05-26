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
    return None


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

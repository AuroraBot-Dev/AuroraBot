"""结构化数据的 I/O 与解析工具。

整合了原子 JSON 文件持久化、LLM 输出的容错解析、
以及 JSON/YAML/TOML 通用结构化文本提取。

作者: [Churk-Ben](https://github.com/Churk-Ben)
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import tomllib
import uuid
from enum import StrEnum
from typing import TYPE_CHECKING, Any

import yaml

if TYPE_CHECKING:
    from pathlib import Path


class _Msg(StrEnum):
    INVALID_JSON_OBJECT = "Invalid JSON object format"


def atomic_write_json(path: Path, value: Any) -> None:
    """原子写入 JSON 数据。

    通过创建临时文件并原子替换来确保数据一致性。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink(missing_ok=True)


def read_json(path: Path) -> Any:
    """从 UTF-8 JSON 文件中读取数据。"""
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def extract_json_from_text(raw: str) -> Any:
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
            return result
    except json.JSONDecodeError:
        pass

    # 尝试匹配首尾花括号
    try:
        result = _safe_parse_json_object(text)
        if isinstance(result, dict):
            return result
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


def _safe_parse_json_object(content: str) -> Any:
    """从文本中提取首个完整 JSON 对象

    找不到时抛出 ValueError
    """
    left = content.find("{")
    right = content.rfind("}")
    if left == -1 or right == -1 or right <= left:
        raise ValueError(_Msg.INVALID_JSON_OBJECT)
    return json.loads(content[left : right + 1])


def parse_structured(text: str | None) -> dict[str, Any]:
    """从文本中提取结构化数据。

    依次尝试 JSON → YAML → TOML，均失败返回空字典。
    """
    if not text or not text.strip():
        return {}
    raw = text.strip()

    for parser, _name in ((json.loads, "JSON"), (yaml.safe_load, "YAML"), (tomllib.loads, "TOML")):
        try:
            result = parser(raw)
            if isinstance(result, dict):
                return result
        except Exception:  # noqa: BLE001
            continue

    return {}


def json_ready(value: Any) -> Any:
    """递归将值转化为 JSON 可序列化形式。"""
    if isinstance(value, dict):
        return {str(key): json_ready(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_ready(item) for item in value]
    if isinstance(value, tuple):
        return [json_ready(item) for item in value]
    if isinstance(value, (dt.date, dt.datetime)):
        return value.isoformat()
    return value

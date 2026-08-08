"""文本命令解析器：基于 ParameterSpec 把斜杠命令解析为规范化 params（RFC 0218 §2）。

文本表示与 REST 表示同构：路径参数即路径段，QUERY/BODY 参数用 ``--key value``
或 ``--key=value``，FLAG 用 ``--key``。解析产物与 REST 入口是同一个 ``params``。
"""

from __future__ import annotations

import json
import shlex
from typing import Any

from src.contracts import OperationSpec, ParameterKind, ParameterLocation, ParameterSpec


class CommandParseError(ValueError):
    """命令文本解析失败。"""


class HelpRequestError(ValueError):
    """命令请求展示用法（--help / -h）。"""


_HELP_FLAGS = ("--help", "-h")


def split_text(raw: str) -> tuple[str, ...]:
    """按 shell 规则分词；失败时抛出 CommandParseError。"""
    try:
        return tuple(shlex.split(raw))
    except ValueError as error:
        raise CommandParseError(str(error)) from error


def match_path(tokens: tuple[str, ...], spec: OperationSpec) -> dict[str, str] | None:
    """尝试把首个 token 作为路径模板匹配，提取路径参数。

    ``/engine/tasks/123`` 匹配 ``/engine/tasks/{task_id}`` -> ``{"task_id": "123"}``。
    """
    raw_path = tokens[0].rstrip("/")
    spec_path = spec.path.rstrip("/")
    raw_segments = raw_path.split("/")
    spec_segments = spec_path.split("/")
    if len(raw_segments) != len(spec_segments):
        return None
    params: dict[str, str] = {}
    for raw_segment, spec_segment in zip(raw_segments, spec_segments, strict=True):
        if spec_segment.startswith("{") and spec_segment.endswith("}"):
            params[spec_segment[1:-1]] = raw_segment
        elif raw_segment != spec_segment:
            return None
    return params


def parse_text(spec: OperationSpec, tokens: tuple[str, ...], path_params: dict[str, str] | None) -> dict[str, Any]:
    """把命令 token 解析为规范化参数 dict。

    Args:
        spec: 目标操作。
        tokens: shlex 分词后的完整 token 序列（含命令名）。
        path_params: 路径参数（完整路径匹配时已提取；别名命令时为 None）。
    """
    params: dict[str, Any] = {}
    if path_params is not None:
        params.update(path_params)
    rest = tokens[1:]
    if any(flag in rest for flag in _HELP_FLAGS):
        raise HelpRequestError
    positional_slots = [p for p in spec.parameters if p.location in {ParameterLocation.PATH, ParameterLocation.BODY}]
    positional_index = 0
    index = 0
    while index < len(rest):
        token = rest[index]
        if token.startswith("--"):
            body = token[2:]
            if "=" in body:
                key, raw_value = body.split("=", 1)
                parameter = spec.parameter(key)
                if parameter is None:
                    raise CommandParseError(f"未知参数: {key}")
                params[key] = coerce_value(raw_value, parameter)
            else:
                parameter = spec.parameter(body)
                if parameter is None:
                    raise CommandParseError(f"未知参数: {body}")
                if parameter.kind is ParameterKind.FLAG:
                    params[body] = True
                else:
                    if index + 1 >= len(rest):
                        raise CommandParseError(f"参数缺少值: {body}")
                    params[body] = coerce_value(rest[index + 1], parameter)
                    index += 1
        else:
            if positional_index >= len(positional_slots):
                raise CommandParseError(f"多余的位置参数: {token}")
            parameter = positional_slots[positional_index]
            if parameter.name in params:
                raise CommandParseError(f"参数重复: {parameter.name}")
            params[parameter.name] = coerce_value(token, parameter)
            positional_index += 1
        index += 1
    return params


def coerce_value(value: Any, parameter: ParameterSpec) -> Any:
    """按参数声明类型转换单个值；失败抛出 CommandParseError。"""
    try:
        if parameter.type == "int":
            return int(value)
        if parameter.type == "float":
            return float(value)
        if parameter.type == "bool":
            if isinstance(value, bool):
                return value
            lowered = str(value).strip().casefold()
            if lowered in {"true", "1", "yes"}:
                return True
            if lowered in {"false", "0", "no"}:
                return False
            raise ValueError(f"invalid bool: {value}")
        if parameter.type == "json":
            if isinstance(value, (dict, list)):
                return value
            return json.loads(str(value))
        return str(value)
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        raise CommandParseError(f"{parameter.name} 需要 {parameter.type} 类型: {value}") from error


def validate_params(spec: OperationSpec, params: dict[str, Any]) -> dict[str, Any]:
    """按声明补默认值并校验必填参数；返回规范化参数副本。"""
    normalized = dict(params)
    for parameter in spec.parameters:
        if parameter.name in normalized:
            continue
        if parameter.required:
            raise CommandParseError(f"缺少必填参数: {parameter.name}")
        if parameter.default is not None:
            normalized[parameter.name] = parameter.default
    return normalized


def usage(spec: OperationSpec) -> str:
    """由参数声明渲染用法串（供 PARSE_ERROR 提示）。"""
    pieces = [f"{spec.method} {spec.path}"]
    if spec.aliases:
        pieces.append(f"别名: {' '.join(spec.aliases)}")
    for parameter in spec.parameters:
        required = "必填" if parameter.required else f"默认 {parameter.default}"
        location = {"path": "路径", "query": "查询", "body": "请求体"}[parameter.location]
        suffix = f" {parameter.help}" if parameter.help else ""
        pieces.append(f"  --{parameter.name} <{parameter.type}> ({location}，{required}){suffix}")
    return "\n".join(pieces)

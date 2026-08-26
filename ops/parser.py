"""把斜杠文本和结构参数解析为同一操作参数。"""

from __future__ import annotations

import json
import shlex
from typing import Any

from ops.contracts import OperationSpec, ParameterKind, ParameterLocation, ParameterSpec


class CommandParseError(ValueError):
    pass


class HelpRequestError(ValueError):
    pass


_HELP_FLAGS = ("--help", "-h")


def split_text(raw: str) -> tuple[str, ...]:
    try:
        return tuple(shlex.split(raw))
    except ValueError as error:
        raise CommandParseError(str(error)) from error


def match_path(tokens: tuple[str, ...], spec: OperationSpec) -> dict[str, str] | None:
    raw_segments = tokens[0].rstrip("/").split("/")
    spec_segments = spec.path.rstrip("/").split("/")
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
    params: dict[str, Any] = {} if path_params is None else dict(path_params)
    rest = tokens[1:]
    if any(flag in rest for flag in _HELP_FLAGS):
        raise HelpRequestError
    positional = [
        parameter
        for parameter in spec.parameters
        if parameter.location in {ParameterLocation.PATH, ParameterLocation.BODY}
    ]
    positional_index = 0
    index = 0
    while index < len(rest):
        token = rest[index]
        if token.startswith("--"):
            index = _parse_named(spec, rest, index, params)
        else:
            if positional_index >= len(positional):
                raise CommandParseError(f"多余的位置参数：{token}")
            parameter = positional[positional_index]
            if parameter.name in params:
                raise CommandParseError(f"参数重复：{parameter.name}")
            params[parameter.name] = coerce_value(token, parameter)
            positional_index += 1
        index += 1
    return params


def _parse_named(spec: OperationSpec, tokens: tuple[str, ...], index: int, params: dict[str, Any]) -> int:
    body = tokens[index][2:]
    if "=" in body:
        key, raw_value = body.split("=", 1)
        parameter = _parameter(spec, key)
        params[key] = coerce_value(raw_value, parameter)
        return index
    parameter = _parameter(spec, body)
    if parameter.kind is ParameterKind.FLAG:
        params[body] = True
        return index
    if index + 1 >= len(tokens):
        raise CommandParseError(f"参数缺少值：{body}")
    params[body] = coerce_value(tokens[index + 1], parameter)
    return index + 1


def _parameter(spec: OperationSpec, name: str) -> ParameterSpec:
    parameter = spec.parameter(name)
    if parameter is None:
        raise CommandParseError(f"未知参数：{name}")
    return parameter


def coerce_value(value: object, parameter: ParameterSpec) -> object:
    try:
        if parameter.type == "int":
            converted: object = int(str(value))
        elif parameter.type == "float":
            converted = float(str(value))
        elif parameter.type == "bool":
            if isinstance(value, bool):
                converted = value
            else:
                lowered = str(value).strip().casefold()
                if lowered in {"true", "1", "yes"}:
                    converted = True
                elif lowered in {"false", "0", "no"}:
                    converted = False
                else:
                    raise ValueError(f"无效布尔值：{value}")
        elif parameter.type == "json":
            converted = value if isinstance(value, (dict, list)) else json.loads(str(value))
        else:
            converted = str(value)
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        raise CommandParseError(f"{parameter.name} 需要 {parameter.type} 类型：{value}") from error
    return converted


def validate_params(spec: OperationSpec, params: dict[str, Any]) -> dict[str, Any]:
    known = {parameter.name for parameter in spec.parameters}
    unknown = sorted(set(params) - known)
    if unknown:
        raise CommandParseError(f"未知参数：{', '.join(unknown)}")
    normalized = dict(params)
    for parameter in spec.parameters:
        if parameter.name in normalized:
            normalized[parameter.name] = coerce_value(normalized[parameter.name], parameter)
        elif parameter.required:
            raise CommandParseError(f"缺少必填参数：{parameter.name}")
        elif parameter.default is not None:
            normalized[parameter.name] = parameter.default
    return normalized


def usage(spec: OperationSpec) -> str:
    pieces = [f"{spec.method} {spec.path}"]
    if spec.aliases:
        pieces.append(f"别名：{' '.join(spec.aliases)}")
    for parameter in spec.parameters:
        required = "必填" if parameter.required else f"默认 {parameter.default}"
        pieces.append(f"  --{parameter.name} <{parameter.type}>（{required}） {parameter.help}".rstrip())
    return "\n".join(pieces)

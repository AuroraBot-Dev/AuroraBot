"""把结构参数校验为同一操作参数。"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ops.contracts import OperationSpec, ParameterSpec


class CommandParseError(ValueError):
    pass


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

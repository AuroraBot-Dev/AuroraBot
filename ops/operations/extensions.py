"""extensions 域操作：内建扩展声明查看与启用状态切换。"""

from __future__ import annotations

from typing import Any

from ops.registry import operation
from src.contracts import OperationResult, ParameterKind, ParameterLocation, ParameterSpec


@operation(
    "GET",
    "/extensions",
    name="extensions.list",
    aliases=("/extensions", "/plugins"),
    summary="内建扩展声明列表（含禁用）",
)
async def extensions_list(context: Any, _params: dict[str, Any]) -> OperationResult:
    extensions = context.runtime.config.extensions()
    return OperationResult.success({"extensions": extensions, "count": len(extensions)})


@operation(
    "POST",
    "/extensions/{extension_id}/enabled",
    name="extensions.set_enabled",
    summary="切换内建扩展启用状态（写入 TOML，重启后生效）",
    parameters=(
        ParameterSpec("extension_id", ParameterLocation.PATH, kind=ParameterKind.POSITIONAL, required=True),
        ParameterSpec("enabled", ParameterLocation.BODY, type="bool", required=True),
    ),
)
async def extensions_set_enabled(context: Any, params: dict[str, Any]) -> OperationResult:
    extension_id = str(params["extension_id"])
    enabled = bool(params["enabled"])
    try:
        result = context.runtime.config.set_extension_enabled(extension_id, enabled=enabled)
    except KeyError as error:
        return OperationResult.failure("NOT_FOUND", str(error))
    except (FileNotFoundError, TypeError, ValueError) as error:
        return OperationResult.failure("CONFIG_ERROR", str(error))
    return OperationResult.success(result)

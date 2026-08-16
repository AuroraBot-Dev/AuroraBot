"""apps 域操作：MCP 应用路由查看与启用状态切换。"""

from __future__ import annotations

from typing import Any

from ops.registry import operation
from src.contracts import OperationResult, ParameterKind, ParameterLocation, ParameterSpec


@operation(
    "GET",
    "/apps",
    name="apps.list",
    aliases=("/apps",),
    summary="MCP 应用路由列表（含禁用）",
)
async def apps_list(context: Any, _params: dict[str, Any]) -> OperationResult:
    apps = context.runtime.config.apps()
    return OperationResult.success({"apps": apps, "count": len(apps)})


@operation(
    "POST",
    "/apps/{package}/enabled",
    name="apps.set_enabled",
    summary="切换 MCP 应用启用状态（写入 TOML，重启后生效）",
    parameters=(
        ParameterSpec("package", ParameterLocation.PATH, kind=ParameterKind.POSITIONAL, required=True),
        ParameterSpec("enabled", ParameterLocation.BODY, type="bool", required=True),
    ),
)
async def apps_set_enabled(context: Any, params: dict[str, Any]) -> OperationResult:
    package = str(params["package"])
    enabled = bool(params["enabled"])
    try:
        result = context.runtime.config.set_app_enabled(package, enabled=enabled)
    except KeyError as error:
        return OperationResult.failure("NOT_FOUND", str(error))
    except (FileNotFoundError, TypeError, ValueError) as error:
        return OperationResult.failure("CONFIG_ERROR", str(error))
    return OperationResult.success(result)

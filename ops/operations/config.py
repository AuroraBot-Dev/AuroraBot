"""配置监测与显式开放的开关操作。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ops.contracts import OperationResult, ParameterKind, ParameterLocation, ParameterSpec
from ops.registry import operation

if TYPE_CHECKING:
    from typing import Any

    from ops.contracts import OperationContext


@operation("GET", "/config", name="config.snapshot", summary="查看配置来源与可改动范围")
async def snapshot(context: OperationContext, params: dict[str, Any]) -> OperationResult:
    _ = params
    return OperationResult.success(context.runtime.config.snapshot())


@operation(
    "GET",
    "/config/{name}",
    name="config.read",
    summary="读取一个已注册的个人 TOML 配置",
    aliases=("/config-show",),
    parameters=(ParameterSpec("name", ParameterLocation.PATH, ParameterKind.POSITIONAL, required=True),),
)
async def read(context: OperationContext, params: dict[str, Any]) -> OperationResult:
    name = str(params["name"])
    document = context.runtime.config.read(name)
    if document is None:
        return OperationResult.failure("NOT_FOUND", f"配置尚未注册：{name}")
    return OperationResult.success(document)


@operation(
    "POST",
    "/apps/{package}/enabled",
    name="config.app_enabled",
    summary="修改一个应用的启用状态",
    aliases=("/app-enable",),
    parameters=(
        ParameterSpec("package", ParameterLocation.PATH, ParameterKind.POSITIONAL, required=True),
        ParameterSpec("enabled", ParameterLocation.BODY, type="bool", required=True, help="true 或 false"),
    ),
)
async def set_app_enabled(context: OperationContext, params: dict[str, Any]) -> OperationResult:
    try:
        result = context.runtime.config.set_app_enabled(str(params["package"]), enabled=bool(params["enabled"]))
    except (KeyError, ValueError) as error:
        return OperationResult.failure("CONFIG_ERROR", str(error))
    return OperationResult.success(result, message="应用配置已更新")


@operation(
    "POST",
    "/extensions/{extension_id}/enabled",
    name="config.extension_enabled",
    summary="修改一个扩展的启用状态",
    aliases=("/extension-enable",),
    parameters=(
        ParameterSpec("extension_id", ParameterLocation.PATH, ParameterKind.POSITIONAL, required=True),
        ParameterSpec("enabled", ParameterLocation.BODY, type="bool", required=True, help="true 或 false"),
    ),
)
async def set_extension_enabled(context: OperationContext, params: dict[str, Any]) -> OperationResult:
    try:
        result = context.runtime.config.set_extension_enabled(
            str(params["extension_id"]), enabled=bool(params["enabled"])
        )
    except (KeyError, ValueError) as error:
        return OperationResult.failure("CONFIG_ERROR", str(error))
    return OperationResult.success(result, message="扩展配置已更新")

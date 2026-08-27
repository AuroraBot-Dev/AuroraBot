"""配置监测与显式开放的开关操作。"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

from ops.contracts import OperationResult, ParameterKind, ParameterLocation, ParameterSpec
from ops.operations import require_port
from ops.registry import operation

if TYPE_CHECKING:
    from typing import Any

    from ops.contracts import OperationContext


@operation(
    "GET",
    "/config",
    name="config.snapshot",
    summary="查看配置来源与可改动范围",
)
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
    "/config/reload",
    name="config.reload",
    summary="重新解析全部个人 TOML 并替换运行时配置；不重组已装配实例",
    aliases=("/reload",),
)
async def reload(context: OperationContext, params: dict[str, Any]) -> OperationResult:
    _ = params
    port, missing = require_port(context.runtime.config_reload, "config_reload")
    if missing is not None:
        return missing
    assert port is not None
    try:
        result = port.reload_config()
    except (FileNotFoundError, OSError, RuntimeError, ValueError) as error:
        return OperationResult.failure("CONFIG_ERROR", str(error))
    world, missing_world = require_port(context.runtime.world, "world")
    if missing_world is None:
        assert world is not None
        await world.record_event(
            event_id=f"ops:config:reload:{uuid4().hex}",
            kind="ops.config.reloaded",
            source="ops",
            summary="个人配置已重新加载",
            scope="aurora:config",
            data={"sources": list(result.get("sources", ()))},
        )
    return OperationResult.success(result)


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
    port, missing = require_port(context.runtime.world, "world")
    if missing is not None:
        return missing
    assert port is not None
    try:
        result = context.runtime.config.set_app_enabled(str(params["package"]), enabled=bool(params["enabled"]))
    except (KeyError, ValueError) as error:
        return OperationResult.failure("CONFIG_ERROR", str(error))
    if result["changed"] is True:
        await port.record_event(
            event_id=f"ops:config:apps:{params['package']}:{uuid4().hex}",
            kind="ops.config.changed",
            source="ops",
            summary=f"应用启用状态已改为 {bool(params['enabled'])}",
            scope="aurora:config",
            data={"source": "apps", "package": str(params["package"]), "enabled": bool(params["enabled"])},
        )
    return OperationResult.success(result)


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
    port, missing = require_port(context.runtime.world, "world")
    if missing is not None:
        return missing
    assert port is not None
    try:
        result = context.runtime.config.set_extension_enabled(
            str(params["extension_id"]), enabled=bool(params["enabled"])
        )
    except (KeyError, ValueError) as error:
        return OperationResult.failure("CONFIG_ERROR", str(error))
    if result["changed"] is True:
        await port.record_event(
            event_id=f"ops:config:extensions:{params['extension_id']}:{uuid4().hex}",
            kind="ops.config.changed",
            source="ops",
            summary=f"扩展启用状态已改为 {bool(params['enabled'])}",
            scope="aurora:config",
            data={
                "source": "extensions",
                "extension_id": str(params["extension_id"]),
                "enabled": bool(params["enabled"]),
            },
        )
    return OperationResult.success(result)

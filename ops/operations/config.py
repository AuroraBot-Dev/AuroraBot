"""配置只读监测。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ops.contracts import OperationResult, ParameterKind, ParameterLocation, ParameterSpec
from ops.registry import operation

if TYPE_CHECKING:
    from typing import Any

    from ops.contracts import OperationContext


@operation(
    "GET",
    "/config",
    name="config.snapshot",
    summary="查看配置来源",
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

"""操作目录与系统自描述。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ops.contracts import (
    OperationControl,
    OperationResult,
    OperationScope,
    ParameterKind,
    ParameterLocation,
    ParameterSpec,
)
from ops.registry import catalog_entries, operation
from ops.utils import LOGO, format_catalog

if TYPE_CHECKING:
    from typing import Any

    from ops.contracts import OperationContext


@operation(
    "GET",
    "/",
    name="system.catalog",
    summary="列出全部可用操作",
    aliases=("/help", "/h"),
    parameters=(ParameterSpec("detail", ParameterLocation.BODY, ParameterKind.FLAG, help="输出完整 JSON"),),
)
async def catalog(context: OperationContext, params: dict[str, Any]) -> OperationResult:
    _ = context
    data = {"operations": catalog_entries()}
    if params.get("detail"):
        return OperationResult.success(data)
    return OperationResult.success(data, message="\n" + LOGO + format_catalog())


@operation(
    "POST",
    "/process/shutdown",
    name="system.shutdown",
    summary="请求停止 AuroraBot 进程",
    aliases=("/shutdown", "/exit", "/quit", "/q"),
)
async def shutdown(context: OperationContext, params: dict[str, Any]) -> OperationResult:
    _ = params
    context.runtime.process.request_shutdown()
    return OperationResult.success(message="已请求停止 AuroraBot。", control=OperationControl.SHUTDOWN_PROCESS)


@operation(
    "POST",
    "/console/clear",
    name="system.clear",
    summary="清空本地终端",
    aliases=("/clear", "/cls"),
    scope=OperationScope.TEXT_ONLY,
)
async def clear(context: OperationContext, params: dict[str, Any]) -> OperationResult:
    _ = context, params
    return OperationResult.success(control=OperationControl.CLEAR_CONSOLE)

"""操作目录与系统自描述。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ops.contracts import OperationControl, OperationResult, OperationScope
from ops.registry import catalog_entries, operation

if TYPE_CHECKING:
    from typing import Any

    from ops.contracts import OperationContext


@operation("GET", "/", name="system.catalog", summary="列出全部可用操作", aliases=("/help", "/h"))
async def catalog(context: OperationContext, params: dict[str, Any]) -> OperationResult:
    _ = context, params
    return OperationResult.success({"operations": catalog_entries()})


@operation(
    "POST",
    "/process/shutdown",
    name="system.shutdown",
    summary="请求停止 AuroraBot 进程",
    aliases=("/shutdown", "/exit"),
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
    aliases=("/clear",),
    scope=OperationScope.TEXT_ONLY,
)
async def clear(context: OperationContext, params: dict[str, Any]) -> OperationResult:
    _ = context, params
    return OperationResult.success(control=OperationControl.CLEAR_CONSOLE)

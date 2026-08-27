"""统一工具目录的监测操作。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ops.contracts import OperationResult, ParameterKind, ParameterLocation, ParameterSpec
from ops.operations import require_port
from ops.registry import operation

if TYPE_CHECKING:
    from typing import Any

    from ops.contracts import OperationContext


@operation(
    "GET",
    "/tools",
    name="tools.catalog",
    summary="列出全部已注册工具",
    aliases=("/tools",),
)
async def catalog(context: OperationContext, params: dict[str, Any]) -> OperationResult:
    _ = params
    port, missing = require_port(context.runtime.tools, "tools")
    if missing is not None:
        return missing
    assert port is not None
    return OperationResult.success(port.tool_catalog())


@operation(
    "GET",
    "/tools/{tool_id}",
    name="tools.tool",
    summary="查看一个已注册工具",
    aliases=("/tool",),
    parameters=(ParameterSpec("tool_id", ParameterLocation.PATH, ParameterKind.POSITIONAL, required=True),),
)
async def detail(context: OperationContext, params: dict[str, Any]) -> OperationResult:
    port, missing = require_port(context.runtime.tools, "tools")
    if missing is not None:
        return missing
    assert port is not None
    result = port.tool_detail(str(params["tool_id"]))
    if result is None:
        return OperationResult.failure("NOT_FOUND", f"工具不存在：{params['tool_id']}")
    return OperationResult.success(result)

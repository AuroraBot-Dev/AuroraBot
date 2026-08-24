"""MCP 连接与冻结工具目录的只读监测操作。"""

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
    "/mcp",
    name="mcp.status",
    summary="查看全部 MCP App 状态与冻结工具目录摘要",
    aliases=("/mcp",),
)
async def status(context: OperationContext, params: dict[str, Any]) -> OperationResult:
    _ = params
    port, missing = require_port(context.runtime.mcp, "mcp")
    if missing is not None:
        return missing
    assert port is not None
    return OperationResult.success(port.mcp_status())


@operation(
    "GET",
    "/mcp/{package}",
    name="mcp.app",
    summary="查看一个 MCP App 的连接状态与冻结工具",
    aliases=("/mcp-app",),
    parameters=(ParameterSpec("package", ParameterLocation.PATH, ParameterKind.POSITIONAL, required=True),),
)
async def app(context: OperationContext, params: dict[str, Any]) -> OperationResult:
    port, missing = require_port(context.runtime.mcp, "mcp")
    if missing is not None:
        return missing
    assert port is not None
    package = str(params["package"])
    result = port.mcp_app(package)
    if result is None:
        return OperationResult.failure("NOT_FOUND", f"MCP App 不存在：{package}")
    return OperationResult.success(result)

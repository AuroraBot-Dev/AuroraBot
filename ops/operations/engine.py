"""AgentTree Engine 的只读状态。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ops.contracts import OperationResult
from ops.operations import require_port
from ops.registry import operation

if TYPE_CHECKING:
    from typing import Any

    from ops.contracts import OperationContext


@operation(
    "GET",
    "/engine/status",
    name="engine.status",
    summary="查看 AgentTree Engine 配置状态",
    aliases=("/status",),
)
async def status(context: OperationContext, params: dict[str, Any]) -> OperationResult:
    _ = params
    port, missing = require_port(context.runtime.engine, "engine")
    if missing is not None:
        return missing
    assert port is not None
    return OperationResult.success(port.engine_status())

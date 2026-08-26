"""节律策略状态与显式唤起判断。"""

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
    "/cadence",
    name="cadence.status",
    summary="查看节律策略状态",
    aliases=("/cadence",),
)
async def status(context: OperationContext, params: dict[str, Any]) -> OperationResult:
    _ = params
    port, missing = require_port(context.runtime.cadence, "cadence")
    if missing is not None:
        return missing
    assert port is not None
    return OperationResult.success(port.cadence_status())


@operation(
    "POST",
    "/cadence/trigger",
    name="cadence.trigger",
    summary="显式执行一次唤起判断",
    aliases=("/cadence-trigger",),
)
async def trigger(context: OperationContext, params: dict[str, Any]) -> OperationResult:
    _ = params
    port, missing = require_port(context.runtime.cadence, "cadence")
    if missing is not None:
        return missing
    assert port is not None
    return OperationResult.success(await port.cadence_trigger())

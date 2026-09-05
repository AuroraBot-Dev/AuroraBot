"""节律策略只读状态。"""

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

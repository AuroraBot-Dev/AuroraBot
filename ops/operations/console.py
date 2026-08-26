"""本地终端的世界线接入状态监测。"""

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
    "/console",
    name="console.status",
    summary="查看终端世界线接入状态",
    aliases=("/console",),
)
async def status(context: OperationContext, params: dict[str, Any]) -> OperationResult:
    _ = params
    port, missing = require_port(context.runtime.console, "console")
    if missing is not None:
        return missing
    assert port is not None
    return OperationResult.success(port.console_status())

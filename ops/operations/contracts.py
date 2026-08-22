"""公共契约子包的只读监测操作。"""

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
    "/contracts",
    name="contracts.status",
    summary="列出公共值对象与端口契约",
    aliases=("/contracts",),
)
async def status(context: OperationContext, params: dict[str, Any]) -> OperationResult:
    _ = params
    port, missing = require_port(context.runtime.contracts, "contracts")
    if missing is not None:
        return missing
    assert port is not None
    return OperationResult.success(port.contracts_status())

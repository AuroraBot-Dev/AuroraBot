"""通用工具子包的只读监测操作。"""

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
    "/utils",
    name="utils.status",
    summary="列出通用工具子包的能力",
    aliases=("/utils",),
)
async def status(context: OperationContext, params: dict[str, Any]) -> OperationResult:
    _ = params
    port, missing = require_port(context.runtime.utils, "utils")
    if missing is not None:
        return missing
    assert port is not None
    return OperationResult.success(port.utils_status())

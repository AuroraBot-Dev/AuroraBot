"""操作目录与系统自描述。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ops.contracts import OperationResult
from ops.registry import catalog_entries, operation

if TYPE_CHECKING:
    from typing import Any

    from ops.contracts import OperationContext


@operation("GET", "/", name="system.catalog", summary="列出全部可用操作", aliases=("/help", "/h"))
async def catalog(context: OperationContext, params: dict[str, Any]) -> OperationResult:
    _ = context, params
    return OperationResult.success({"operations": catalog_entries()})

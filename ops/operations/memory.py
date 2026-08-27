"""世界线记忆快照的只读监测操作。"""

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
    "/memory",
    name="memory.snapshot",
    summary="查看最近时间窗口内活跃 scope 的最新提交记忆",
    aliases=("/memory",),
)
async def snapshot(context: OperationContext, params: dict[str, Any]) -> OperationResult:
    _ = params
    port, missing = require_port(context.runtime.memory, "memory")
    if missing is not None:
        return missing
    assert port is not None
    return OperationResult.success(await port.memory_snapshot())

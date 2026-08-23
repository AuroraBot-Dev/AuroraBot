"""世界线连续事件流与提交正文的监测操作。"""

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
    "/world/stream",
    name="world.stream",
    summary="按全局游标读取连续世界事件流",
    aliases=("/world-stream",),
    parameters=(
        ParameterSpec(
            "after",
            ParameterLocation.QUERY,
            type="int",
            default=0,
            help="全局游标，只返回 insertion > after",
        ),
        ParameterSpec("limit", ParameterLocation.QUERY, type="int", default=64, help="每页最多返回的事件数"),
    ),
)
async def stream(context: OperationContext, params: dict[str, Any]) -> OperationResult:
    port, missing = require_port(context.runtime.world, "world")
    if missing is not None:
        return missing
    assert port is not None
    try:
        return OperationResult.success(await port.world_stream(after=int(params["after"]), limit=int(params["limit"])))
    except ValueError as error:
        return OperationResult.failure("INVALID_STREAM", str(error))


@operation(
    "GET",
    "/world/commits/{commit_id}",
    name="world.commit",
    summary="按 commit id 读取一次世界提交正文",
    aliases=("/world-commit",),
    parameters=(ParameterSpec("commit_id", ParameterLocation.PATH, ParameterKind.POSITIONAL, required=True),),
)
async def commit(context: OperationContext, params: dict[str, Any]) -> OperationResult:
    port, missing = require_port(context.runtime.world, "world")
    if missing is not None:
        return missing
    assert port is not None
    result = await port.world_commit(str(params["commit_id"]))
    if result is None:
        return OperationResult.failure("NOT_FOUND", f"世界提交不存在：{params['commit_id']}")
    return OperationResult.success(result)

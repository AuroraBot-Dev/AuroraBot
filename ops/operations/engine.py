"""AgentTree 运行监测与新运行入口。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ops.contracts import OperationResult, ParameterKind, ParameterLocation, ParameterSpec
from ops.registry import operation

if TYPE_CHECKING:
    from typing import Any

    from ops.contracts import OperationContext

_MAX_TREE_LIST_LIMIT = 1000


@operation("GET", "/engine/status", name="engine.status", summary="查看 AgentTree 运行时状态", aliases=("/status",))
async def status(context: OperationContext, params: dict[str, Any]) -> OperationResult:
    _ = params
    return OperationResult.success(context.runtime.engine.runtime_status())


@operation(
    "GET",
    "/trees",
    name="engine.trees",
    summary="列出已观测的 AgentTree",
    parameters=(
        ParameterSpec("status", ParameterLocation.QUERY, help="按 running/completed/failed 过滤"),
        ParameterSpec("limit", ParameterLocation.QUERY, type="int", default=64, help="最多返回的树数量"),
    ),
)
async def trees(context: OperationContext, params: dict[str, Any]) -> OperationResult:
    status_filter = params.get("status")
    limit = int(params["limit"])
    if limit < 1 or limit > _MAX_TREE_LIST_LIMIT:
        return OperationResult.failure("INVALID_LIMIT", "limit 必须在 1 到 1000 之间")
    return OperationResult.success(
        {"trees": context.runtime.engine.list_trees(status=str(status_filter) if status_filter else None, limit=limit)}
    )


@operation(
    "GET",
    "/trees/{tree_id}",
    name="engine.tree",
    summary="查看一棵 AgentTree 的完整快照",
    parameters=(ParameterSpec("tree_id", ParameterLocation.PATH, ParameterKind.POSITIONAL, required=True),),
)
async def tree(context: OperationContext, params: dict[str, Any]) -> OperationResult:
    tree_id = str(params["tree_id"])
    detail = context.runtime.engine.tree_detail(tree_id)
    if detail is None:
        return OperationResult.failure("NOT_FOUND", f"AgentTree 不存在：{tree_id}")
    return OperationResult.success(detail)


@operation(
    "GET",
    "/trees/{tree_id}/nodes/{node_id}",
    name="engine.node",
    summary="查看 AgentTree 中的一个 Agent 节点",
    parameters=(
        ParameterSpec("tree_id", ParameterLocation.PATH, ParameterKind.POSITIONAL, required=True),
        ParameterSpec("node_id", ParameterLocation.PATH, ParameterKind.POSITIONAL, required=True),
    ),
)
async def node(context: OperationContext, params: dict[str, Any]) -> OperationResult:
    tree_id = str(params["tree_id"])
    node_id = str(params["node_id"])
    detail = context.runtime.engine.node_detail(tree_id, node_id)
    if detail is None:
        return OperationResult.failure("NOT_FOUND", f"Agent 节点不存在：{tree_id}/{node_id}")
    return OperationResult.success(detail)


@operation(
    "POST",
    "/trees",
    name="engine.start",
    summary="启动一棵新的 AgentTree",
    aliases=("/run",),
    parameters=(
        ParameterSpec("message", ParameterLocation.BODY, ParameterKind.POSITIONAL, required=True),
        ParameterSpec("tree_id", ParameterLocation.BODY, help="可选的运行标识"),
    ),
)
async def start(context: OperationContext, params: dict[str, Any]) -> OperationResult:
    try:
        result = await context.runtime.engine.start_tree(
            str(params["message"]), tree_id=str(params["tree_id"]) if params.get("tree_id") else None
        )
    except ValueError as error:
        return OperationResult.failure("INVALID_TREE", str(error))
    return OperationResult.success(result, message="AgentTree 运行完成")

"""Agent 目录与特化原型的监测操作。"""

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
    "/agents",
    name="agents.catalog",
    summary="列出全部 Agent definition",
    aliases=("/agents",),
)
async def catalog(context: OperationContext, params: dict[str, Any]) -> OperationResult:
    _ = params
    port, missing = require_port(context.runtime.agents, "agents")
    if missing is not None:
        return missing
    assert port is not None
    return OperationResult.success(port.agent_catalog())


@operation(
    "GET",
    "/agents/{agent_id}",
    name="agents.agent",
    summary="查看一个 Agent definition",
    aliases=("/agent",),
    parameters=(ParameterSpec("agent_id", ParameterLocation.PATH, ParameterKind.POSITIONAL, required=True),),
)
async def detail(context: OperationContext, params: dict[str, Any]) -> OperationResult:
    port, missing = require_port(context.runtime.agents, "agents")
    if missing is not None:
        return missing
    assert port is not None
    result = port.agent_detail(str(params["agent_id"]))
    if result is None:
        return OperationResult.failure("NOT_FOUND", f"Agent 不存在：{params['agent_id']}")
    return OperationResult.success(result)


@operation(
    "GET",
    "/agents/{agent_id}/tools",
    name="agents.tools",
    summary="查看一个 Agent definition 的可见工具",
    parameters=(ParameterSpec("agent_id", ParameterLocation.PATH, ParameterKind.POSITIONAL, required=True),),
)
async def tools(context: OperationContext, params: dict[str, Any]) -> OperationResult:
    port, missing = require_port(context.runtime.agents, "agents")
    if missing is not None:
        return missing
    assert port is not None
    result = port.agent_detail(str(params["agent_id"]))
    if result is None:
        return OperationResult.failure("NOT_FOUND", f"Agent 不存在：{params['agent_id']}")
    return OperationResult.success({"agent_id": result["definition_id"], "tools": result["tools"]})

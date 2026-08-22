"""模型网关配置的只读监测操作。"""

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
    "/models",
    name="ai.models",
    summary="列出模型 provider 与 endpoint",
    aliases=("/models",),
)
async def catalog(context: OperationContext, params: dict[str, Any]) -> OperationResult:
    _ = params
    port, missing = require_port(context.runtime.ai, "ai")
    if missing is not None:
        return missing
    assert port is not None
    return OperationResult.success(port.model_catalog())


@operation(
    "GET",
    "/models/{endpoint_id}",
    name="ai.model",
    summary="查看一个模型 endpoint",
    aliases=("/model",),
    parameters=(ParameterSpec("endpoint_id", ParameterLocation.PATH, ParameterKind.POSITIONAL, required=True),),
)
async def detail(context: OperationContext, params: dict[str, Any]) -> OperationResult:
    port, missing = require_port(context.runtime.ai, "ai")
    if missing is not None:
        return missing
    assert port is not None
    result = port.model_detail(str(params["endpoint_id"]))
    if result is None:
        return OperationResult.failure("NOT_FOUND", f"模型 endpoint 不存在：{params['endpoint_id']}")
    return OperationResult.success(result)

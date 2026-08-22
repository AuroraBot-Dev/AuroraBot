"""提示词目录的只读监测操作。"""

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
    "/prompts",
    name="prompts.catalog",
    summary="列出全局 system 与 Agent 提示词",
    aliases=("/prompts",),
)
async def catalog(context: OperationContext, params: dict[str, Any]) -> OperationResult:
    _ = params
    port, missing = require_port(context.runtime.prompt, "prompt")
    if missing is not None:
        return missing
    assert port is not None
    return OperationResult.success(port.prompt_catalog())


@operation(
    "GET",
    "/prompts/{prompt_id}",
    name="prompts.prompt",
    summary="查看一个提示词正文",
    aliases=("/prompt",),
    parameters=(ParameterSpec("prompt_id", ParameterLocation.PATH, ParameterKind.POSITIONAL, required=True),),
)
async def detail(context: OperationContext, params: dict[str, Any]) -> OperationResult:
    port, missing = require_port(context.runtime.prompt, "prompt")
    if missing is not None:
        return missing
    assert port is not None
    result = port.prompt_detail(str(params["prompt_id"]))
    if result is None:
        return OperationResult.failure("NOT_FOUND", f"提示词不存在：{params['prompt_id']}")
    return OperationResult.success(result)

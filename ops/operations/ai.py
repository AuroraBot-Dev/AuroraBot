"""ai 域操作：模型网关只读观察（RFC 0218 §3）。"""

from __future__ import annotations

from typing import Any

from ops.registry import operation
from src.contracts import OperationResult


@operation("GET", "/ai/cost", name="ai.cost", aliases=("/cost",), summary="模型费用分类统计")
async def ai_cost(context: Any, _params: dict[str, Any]) -> OperationResult:
    return OperationResult.success(await context.runtime.ai.cost())


@operation("GET", "/ai/models", name="ai.models", aliases=("/models",), summary="角色-模型绑定、能力与模态")
async def ai_models(context: Any, _params: dict[str, Any]) -> OperationResult:
    models = await context.runtime.ai.models()
    return OperationResult.success({"models": models, "count": len(models)})


@operation("GET", "/ai/roles", name="ai.roles", aliases=("/roles",), summary="角色目录")
async def ai_roles(context: Any, _params: dict[str, Any]) -> OperationResult:
    roles = context.runtime.ai.roles()
    return OperationResult.success({"roles": roles, "count": len(roles)})

"""memory 域操作：记忆引擎只读观察（RFC 0218 §3）。"""

from __future__ import annotations

from typing import Any

from src.contracts import OperationResult, ParameterLocation, ParameterSpec

from ops.registry import operation


@operation(
    "GET",
    "/memory/history",
    name="memory.history",
    summary="记忆历史（窗口、概要与长期事实）",
    parameters=(
        ParameterSpec("scope", ParameterLocation.QUERY),
        ParameterSpec("limit", ParameterLocation.QUERY, type="int", default=32),
    ),
)
async def memory_history(context: Any, params: dict[str, Any]) -> OperationResult:
    return OperationResult.success(
        context.runtime.memory.history(scope=params.get("scope"), limit=params.get("limit", 32))
    )


@operation(
    "GET",
    "/memory/search",
    name="memory.search",
    summary="记忆检索（词项匹配）",
    parameters=(
        ParameterSpec("query", ParameterLocation.QUERY, required=True),
        ParameterSpec("scope", ParameterLocation.QUERY),
        ParameterSpec("limit", ParameterLocation.QUERY, type="int", default=8),
    ),
)
async def memory_search(context: Any, params: dict[str, Any]) -> OperationResult:
    query = str(params["query"])
    if not query.strip():
        return OperationResult.failure("PARSE_ERROR", "query 不能为空")
    results = context.runtime.memory.search(query, scope=params.get("scope"), limit=params.get("limit", 8))
    return OperationResult.success({"results": results, "count": len(results)})


@operation("GET", "/memory/status", name="memory.status", summary="记忆存储统计")
async def memory_status(context: Any, _params: dict[str, Any]) -> OperationResult:
    return OperationResult.success(context.runtime.memory.status())

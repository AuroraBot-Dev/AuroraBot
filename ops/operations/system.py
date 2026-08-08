"""system 域操作：目录自描述（RFC 0218 §3）。"""

from __future__ import annotations

from typing import Any

from src.contracts import OperationResult

from ops.registry import catalog_entries, operation


@operation("GET", "/", name="system.info", aliases=("/help", "/h"), summary="操作目录自描述")
async def system_info(_context: Any, _params: dict[str, Any]) -> OperationResult:
    return OperationResult.success({"operations": catalog_entries(), "count": len(catalog_entries())})

"""能力路由表与活动派发。

ToolRegistry 是 capability ID → 执行器的一对一路由表：
- 模型输出一致的 ``aur.*`` 工具 ID；
- 活动行直接构造执行请求并分派给对应 executor；
- executor 执行完成后经 AMP 提交 ``tool.{status}`` 回执（engine 无内部完成端口）；
- 恢复 = 重新派发执行（request_id 幂等保证回执去重）。
"""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Any

from src.contracts import (
    CapabilityCatalogSnapshot,
    ToolExecutionRequest,
    ToolExecutorBinding,
    ToolRequest,
)

if TYPE_CHECKING:
    from src.engine.store import SQLiteRuntimeStore


class ToolBindingError(RuntimeError):
    """活动工具执行器无法形成唯一不可变目录时抛出。"""


_ALREADY_BOUND = "Tool executors are already bound"
_NOT_BOUND = "Tool executors have not been bound"
_NO_EXECUTOR = "no active executor for {capability}"


class ToolRegistry:
    """工具注册表：按 capability ID 将活动请求分派给已绑定的执行器。

    执行器执行完成后自行提交回执 AMP；本类只在执行器抛异常时兜底提交
    failed 回执，避免活动永久挂起。
    """

    def __init__(self, store: "SQLiteRuntimeStore") -> None:
        self._store = store
        self._bindings: dict[str, ToolExecutorBinding] | None = None

    @property
    def capability_catalog(self) -> CapabilityCatalogSnapshot:
        """返回当前绑定执行器对应的不可变能力目录快照。"""
        if self._bindings is None:
            return CapabilityCatalogSnapshot()
        return CapabilityCatalogSnapshot(tuple(item.capability for item in self._bindings.values()))

    def bind(self, bindings: tuple[ToolExecutorBinding, ...]) -> CapabilityCatalogSnapshot:
        """绑定工具执行器集合（仅限一次），形成一对一路由表。"""
        if self._bindings is not None:
            raise ToolBindingError(_ALREADY_BOUND)
        by_capability: dict[str, ToolExecutorBinding] = {}
        for binding in bindings:
            capability = binding.capability.id
            if capability in by_capability:
                message = f"duplicate active Tool capability: {capability}"
                raise ToolBindingError(message)
            by_capability[capability] = binding
        self._bindings = dict(sorted(by_capability.items()))
        return self.capability_catalog

    async def recover_pending(self) -> tuple[str, ...]:
        """重新派发所有 PROCESSING 工具活动（重启后重跑执行，回执幂等去重）。"""
        if self._bindings is None:
            raise ToolBindingError(_NOT_BOUND)
        return await self._dispatch(self._store.tool_recovery_activities())

    async def execute_pending(self, limit: int) -> tuple[str, ...]:
        """派发所有待处理的工具活动，返回派发数量对应的回执计数。"""
        if self._bindings is None:
            raise ToolBindingError(_NOT_BOUND)
        return await self._dispatch(self._store.claim_tool_activities(limit))

    async def _dispatch(self, rows: tuple[Any, ...]) -> tuple[str, ...]:
        """并发派发多个活动行到对应执行器；异常与无匹配时兜底提交 failed 回执。"""
        if not rows:
            return ()

        async def dispatch_one(row: Any) -> str:
            assert self._bindings is not None
            request = _execution_request(row)
            binding = self._bindings.get(request.capability)
            if binding is None:
                await self._fail_receipt(request, _NO_EXECUTOR.format(capability=request.capability))
                return request.request_id
            try:
                await binding.executor.execute_tool(request)
            except Exception as error:  # noqa: BLE001 - executor 失败必须有确定性回执
                await self._fail_receipt(request, f"{type(error).__name__}: {error}")
            return request.request_id

        results = await asyncio.gather(*(dispatch_one(row) for row in rows), return_exceptions=True)
        failures = [result for result in results if isinstance(result, BaseException)]
        if failures:
            raise failures[0]
        return tuple(results)  # type: ignore[return-value]

    async def _fail_receipt(self, request: ToolExecutionRequest, error: str) -> None:
        """兜底提交 failed 回执：完成活动并投递 tool.failed 消息。"""
        self._store.consume_tool_receipt(
            request_id=request.request_id,
            event_type="tool.failed",
            summary="tool unavailable",
            payload={
                "request_id": request.request_id,
                "capability": request.capability,
                "result": None,
                "error": error,
                "source": {"app": "engine.tool_registry", "instance": "unavailable"},
            },
        )


def _execution_request(row: Any) -> ToolExecutionRequest:
    """从持久化活动实体构造工具执行请求（无 ToolLease 中转）。"""
    raw = json.loads(row.request_json)
    request = ToolRequest.from_dict(raw)
    return ToolExecutionRequest(
        request_id=str(row.idempotency_key),
        session_id=str(raw.get("session_id", "")),
        capability=request.capability,
        parameters=request.parameters,
    )

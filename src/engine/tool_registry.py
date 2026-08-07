"""路由 engine 工具租约并发出确定性三态回执。"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from src.contracts import (
    CapabilityCatalogSnapshot,
    ToolExecutionRequest,
    ToolExecutorBinding,
    ToolLease,
    ToolOutcome,
    ToolOutcomeStatus,
)

if TYPE_CHECKING:
    from src.contracts.ports import ToolCompletionPort, ToolQueuePort


class ToolBindingError(RuntimeError):
    """活动工具执行器无法形成唯一不可变目录时抛出。"""


_ALREADY_BOUND = "Tool executors are already bound"
_NOT_BOUND = "Tool executors have not been bound"


class ToolRegistry:
    """工具注册表：将 engine 工具租约分派给已绑定的执行器并回写完成状态。

    支持首次派发与恢复两种模式，对无匹配执行器的请求返回确定性失败/未知回执。
    """

    def __init__(self, queue: ToolQueuePort, completion: ToolCompletionPort) -> None:
        self._queue = queue
        self._completion = completion
        self._bindings: dict[str, ToolExecutorBinding] | None = None

    @property
    def capability_catalog(self) -> CapabilityCatalogSnapshot:
        """返回当前绑定执行器对应的不可变能力目录快照。"""
        if self._bindings is None:
            return CapabilityCatalogSnapshot()
        return CapabilityCatalogSnapshot(tuple(item.capability for item in self._bindings.values()))

    def bind(self, bindings: tuple[ToolExecutorBinding, ...]) -> CapabilityCatalogSnapshot:
        """绑定外部工具执行器集合（仅限一次），不可重复绑定。"""
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

    async def recover_pending(self) -> int:
        """恢复所有"处理中"状态的工具请求，返回恢复数量。"""
        if self._bindings is None:
            raise ToolBindingError(_NOT_BOUND)
        leases = await self._queue.tool_recovery_requests()
        await self._dispatch_many(leases, recovery=True)
        return len(leases)

    async def execute_pending(self) -> int:
        """派发所有"待处理"的工具请求，返回派发数量。"""
        if self._bindings is None:
            raise ToolBindingError(_NOT_BOUND)
        leases = await self._queue.claim_tool_requests()
        await self._dispatch_many(leases, recovery=False)
        return len(leases)

    async def _dispatch_many(self, leases: tuple[ToolLease, ...], *, recovery: bool) -> None:
        """并发派发多个租约，任一失败即抛出首个异常。"""
        results = await asyncio.gather(
            *(self._dispatch_one(lease, recovery=recovery) for lease in leases), return_exceptions=True
        )
        failures = [result for result in results if isinstance(result, BaseException)]
        if failures:
            raise failures[0]

    async def _dispatch_one(self, lease: ToolLease, *, recovery: bool) -> None:
        """派发单个工具租约到对应执行器，无匹配时生成确定性回执。"""
        assert self._bindings is not None
        binding = self._bindings.get(lease.capability)
        request = ToolExecutionRequest(lease.request_id, lease.session_id, lease.capability, lease.parameters)
        if binding is None:
            status = ToolOutcomeStatus.UNKNOWN if recovery else ToolOutcomeStatus.FAILED
            outcome = ToolOutcome(status, f"No active executor for {lease.capability}", error="Tool unavailable")
            source_app, source_instance = "engine.tool_registry", "unavailable"
        elif recovery and binding.recovery is None:
            outcome = ToolOutcome(
                ToolOutcomeStatus.UNKNOWN, f"Tool result unknown: {lease.capability}", error="recovery unsupported"
            )
            source_app, source_instance = binding.source_app, binding.source_instance
        else:
            try:
                if recovery:
                    assert binding.recovery is not None
                    outcome = await binding.recovery.recover_tool(request)
                else:
                    outcome = await binding.executor.execute_tool(request)
            except Exception as error:  # noqa: BLE001 - executor failures have an explicit unknown outcome
                outcome = ToolOutcome(
                    ToolOutcomeStatus.UNKNOWN,
                    f"Tool result unknown: {lease.capability}",
                    error=f"{type(error).__name__}: {error}",
                )
            source_app, source_instance = binding.source_app, binding.source_instance
        await self._completion.complete_tool(
            request_id=lease.request_id,
            capability=lease.capability,
            status=outcome.status,
            summary=outcome.summary,
            result=outcome.result,
            error=outcome.error,
            source_app=source_app,
            source_instance=source_instance,
        )

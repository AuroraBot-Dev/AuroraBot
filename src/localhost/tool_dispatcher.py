"""Route unified Kernel Tool leases and emit deterministic three-state receipts."""

from __future__ import annotations

import asyncio

from src.contracts.agent import CapabilityCatalogSnapshot, ToolLease
from src.localhost.ports import (
    ToolCompletionPort,
    ToolExecutionRequest,
    ToolExecutorBinding,
    ToolOutcome,
    ToolQueuePort,
)


class ToolBindingError(RuntimeError):
    """Raised when active Tool executors cannot form one immutable catalog."""


_ALREADY_BOUND = "Tool executors are already bound"
_NOT_BOUND = "Tool executors have not been bound"


class ToolDispatcher:
    def __init__(self, queue: ToolQueuePort, completion: ToolCompletionPort) -> None:
        self._queue = queue
        self._completion = completion
        self._bindings: dict[str, ToolExecutorBinding] | None = None

    @property
    def capability_catalog(self) -> CapabilityCatalogSnapshot:
        if self._bindings is None:
            return CapabilityCatalogSnapshot()
        return CapabilityCatalogSnapshot(tuple(item.capability for item in self._bindings.values()))

    def bind(self, bindings: tuple[ToolExecutorBinding, ...]) -> CapabilityCatalogSnapshot:
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

    async def recover_processing_tools(self) -> int:
        if self._bindings is None:
            raise ToolBindingError(_NOT_BOUND)
        leases = await self._queue.tool_recovery_requests()
        await self._dispatch_many(leases, recovery=True)
        return len(leases)

    async def dispatch_pending_tools(self) -> int:
        if self._bindings is None:
            raise ToolBindingError(_NOT_BOUND)
        leases = await self._queue.claim_tool_requests()
        await self._dispatch_many(leases, recovery=False)
        return len(leases)

    async def _dispatch_many(self, leases: tuple[ToolLease, ...], *, recovery: bool) -> None:
        results = await asyncio.gather(
            *(self._dispatch_one(lease, recovery=recovery) for lease in leases), return_exceptions=True
        )
        failures = [result for result in results if isinstance(result, BaseException)]
        if failures:
            raise failures[0]

    async def _dispatch_one(self, lease: ToolLease, *, recovery: bool) -> None:
        assert self._bindings is not None
        binding = self._bindings.get(lease.capability)
        request = ToolExecutionRequest(lease.request_id, lease.session_id, lease.capability, lease.parameters)
        if binding is None:
            status = "unknown" if recovery else "failed"
            outcome = ToolOutcome(status, f"No active executor for {lease.capability}", error="Tool unavailable")
            source_app, source_instance = "localhost.tool_dispatcher", "unavailable"
        elif recovery and binding.recovery is None:
            outcome = ToolOutcome("unknown", f"Tool result unknown: {lease.capability}", error="recovery unsupported")
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
                    "unknown",
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

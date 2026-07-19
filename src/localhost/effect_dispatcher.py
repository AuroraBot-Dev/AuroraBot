"""Route Kernel effect leases to active Platform executors and emit AMP receipts."""

from __future__ import annotations

import asyncio

from src.contracts.agent import CapabilityCatalogSnapshot, EffectLease, EffectQueue
from src.contracts.amp import new_amp
from src.localhost.ports import (
    EffectExecutionRequest,
    EffectExecutorBinding,
    EffectOutcome,
    ExternalAmpIngressPort,
)
from src.utils.log_utils import get_logger

logger = get_logger("aurora.localhost.effects")


class EffectBindingError(RuntimeError):
    """Raised when active effect executors cannot form one immutable catalog."""


class EffectDispatcher:
    """Own effect claiming, unique capability routing, and durable receipt ingress."""

    def __init__(self, queue: EffectQueue, ingress: ExternalAmpIngressPort) -> None:
        self._queue = queue
        self._ingress = ingress
        self._bindings: dict[str, EffectExecutorBinding] | None = None

    @property
    def capability_catalog(self) -> CapabilityCatalogSnapshot:
        if self._bindings is None:
            return CapabilityCatalogSnapshot()
        return CapabilityCatalogSnapshot(tuple(binding.capability for binding in self._bindings.values()))

    def bind(self, bindings: tuple[EffectExecutorBinding, ...]) -> CapabilityCatalogSnapshot:
        if self._bindings is not None:
            raise EffectBindingError("effect executors are already bound")
        by_capability: dict[str, EffectExecutorBinding] = {}
        for binding in bindings:
            capability = binding.capability.id
            if capability in by_capability:
                raise EffectBindingError(f"duplicate active effect capability: {capability}")
            by_capability[capability] = binding
        self._bindings = dict(sorted(by_capability.items()))
        return self.capability_catalog

    async def dispatch_pending_effects(self) -> int:
        if self._bindings is None:
            raise EffectBindingError("effect executors have not been bound")
        leases = await self._queue.claim_effect_requests()
        if not leases:
            return 0
        results = await asyncio.gather(*(self._dispatch_one(lease) for lease in leases), return_exceptions=True)
        failures = [result for result in results if isinstance(result, BaseException)]
        if failures:
            raise failures[0]
        return len(leases)

    async def _dispatch_one(self, lease: EffectLease) -> None:
        assert self._bindings is not None
        binding = self._bindings.get(lease.capability)
        if binding is None:
            outcome = EffectOutcome(
                succeeded=False,
                summary=f"No active executor for {lease.capability}",
                error=f"unavailable effect capability: {lease.capability}",
            )
            source_app = "localhost.effect_dispatcher"
            source_instance = "unavailable"
        else:
            try:
                outcome = await binding.executor.execute_effect(
                    EffectExecutionRequest(
                        request_id=lease.request_id,
                        session_id=lease.session_id,
                        capability=lease.capability,
                        parameters=lease.parameters,
                    )
                )
            except Exception as error:
                outcome = EffectOutcome(
                    succeeded=False,
                    summary=f"Effect executor failed: {lease.capability}",
                    error=f"{type(error).__name__}: {error}",
                )
            source_app = binding.source_app
            source_instance = binding.source_instance
        event_type = "effect.succeeded" if outcome.succeeded else "effect.failed"
        data: dict[str, object] = {
            "request_id": lease.request_id,
            "capability": lease.capability,
        }
        if outcome.succeeded:
            data["result"] = outcome.result or {}
        else:
            data["error"] = outcome.error
        receipt = new_amp(
            event_type=event_type,
            session_id=lease.session_id,
            summary=outcome.summary,
            data=data,
            source_app=source_app,
            source_instance=source_instance,
        )
        # Ingress owns persistence and wake-up. A failed write must remain visible to the caller.
        await self._ingress.submit_amp(receipt.to_dict())
        logger.info(
            "effect receipt emitted activity_id=%s task_id=%s request_id=%s capability=%s outcome=%s",
            lease.activity_id,
            lease.task_id,
            lease.request_id,
            lease.capability,
            event_type,
        )

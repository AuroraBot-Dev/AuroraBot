"""Route Kernel Publication leases and emit deterministic three-state AMP receipts."""

from __future__ import annotations

import asyncio
from uuid import NAMESPACE_URL, uuid5

from src.contracts.agent import CapabilityCatalogSnapshot, PublicationLease
from src.contracts.amp import new_amp
from src.localhost.ports import (
    ExternalAmpIngressPort,
    PublicationExecutionRequest,
    PublicationExecutorBinding,
    PublicationOutcome,
    PublicationQueuePort,
)
from src.utils.log_utils import get_logger

logger = get_logger("aurora.localhost.publications")


class PublicationBindingError(RuntimeError):
    """Raised when Publication executors cannot form one immutable catalog."""


class PublicationDispatcher:
    """Own Publication recovery, claiming, unique routing, and receipt ingress."""

    def __init__(self, queue: PublicationQueuePort, ingress: ExternalAmpIngressPort) -> None:
        self._queue = queue
        self._ingress = ingress
        self._bindings: dict[str, PublicationExecutorBinding] | None = None
        self._recovery_complete = False

    @property
    def capability_catalog(self) -> CapabilityCatalogSnapshot:
        if self._bindings is None:
            return CapabilityCatalogSnapshot()
        return CapabilityCatalogSnapshot(tuple(binding.capability for binding in self._bindings.values()))

    def bind(self, bindings: tuple[PublicationExecutorBinding, ...]) -> CapabilityCatalogSnapshot:
        if self._bindings is not None:
            raise PublicationBindingError("Publication executors are already bound")
        by_capability: dict[str, PublicationExecutorBinding] = {}
        endpoints: set[tuple[str, str]] = set()
        for binding in bindings:
            descriptor = binding.capability
            if descriptor.kind != "publication" or descriptor.endpoint is None or descriptor.operation is None:
                raise PublicationBindingError(f"invalid Publication capability: {descriptor.id}")
            if descriptor.id in by_capability:
                raise PublicationBindingError(f"duplicate active Publication capability: {descriptor.id}")
            endpoint_operation = (descriptor.endpoint, descriptor.operation)
            if endpoint_operation in endpoints:
                raise PublicationBindingError(
                    f"duplicate active Publication endpoint operation: {descriptor.endpoint}/{descriptor.operation}"
                )
            by_capability[descriptor.id] = binding
            endpoints.add(endpoint_operation)
        self._bindings = dict(sorted(by_capability.items()))
        return self.capability_catalog

    async def recover_processing_publications(self) -> int:
        if self._bindings is None:
            raise PublicationBindingError("Publication executors have not been bound")
        if self._recovery_complete:
            return 0
        leases = await self._queue.publication_recovery_requests()
        await self._dispatch_many(leases, recovery=True)
        self._recovery_complete = True
        return len(leases)

    async def dispatch_pending_publications(self) -> int:
        if self._bindings is None:
            raise PublicationBindingError("Publication executors have not been bound")
        leases = await self._queue.claim_publication_requests()
        await self._dispatch_many(leases, recovery=False)
        return len(leases)

    async def _dispatch_many(self, leases: tuple[PublicationLease, ...], *, recovery: bool) -> None:
        if not leases:
            return
        results = await asyncio.gather(
            *(self._dispatch_one(lease, recovery=recovery) for lease in leases),
            return_exceptions=True,
        )
        failures = [result for result in results if isinstance(result, BaseException)]
        if failures:
            raise failures[0]

    async def _dispatch_one(self, lease: PublicationLease, *, recovery: bool) -> None:
        assert self._bindings is not None
        binding = self._bindings.get(lease.capability)
        request = _execution_request(lease)
        if binding is None or binding.capability.endpoint != lease.endpoint_id:
            outcome = PublicationOutcome(
                "failed",
                f"No active Publication executor for {lease.capability}",
                error=f"unavailable Publication capability: {lease.capability}",
            )
            source_app = "localhost.publication_dispatcher"
            source_instance = "unavailable"
        else:
            try:
                if recovery:
                    outcome = await binding.recovery.recover_publication(request)
                else:
                    outcome = await binding.executor.execute_publication(request)
            except Exception as error:
                outcome = PublicationOutcome(
                    "delivery_unknown",
                    f"Publication delivery is unknown: {lease.capability}",
                    error=f"{type(error).__name__}: {error}",
                )
            source_app = binding.source_app
            source_instance = binding.source_instance
        await self._emit_receipt(lease, outcome, source_app, source_instance)

    async def _emit_receipt(
        self,
        lease: PublicationLease,
        outcome: PublicationOutcome,
        source_app: str,
        source_instance: str,
    ) -> None:
        event_type = {
            "accepted": "publication.succeeded",
            "failed": "publication.failed",
            "delivery_unknown": "publication.delivery_unknown",
        }[outcome.status]
        data: dict[str, object] = {
            "request_id": lease.request_id,
            "capability": lease.capability,
            "endpoint_id": lease.endpoint_id,
            "operation": lease.operation,
        }
        if outcome.status == "accepted":
            data["result"] = {"external_message_id": outcome.external_message_id}
        else:
            data["error"] = outcome.error
        receipt = new_amp(
            event_type=event_type,
            session_id=lease.task_id,
            summary=outcome.summary,
            data=data,
            source_app=source_app,
            source_instance=source_instance,
        ).to_dict()
        receipt["header"]["message_id"] = str(
            uuid5(NAMESPACE_URL, f"aurora-publication-receipt:{lease.request_id}:{event_type}")
        )
        await self._ingress.submit_amp(receipt)
        logger.info(
            "Publication receipt emitted activity_id=%s task_id=%s request_id=%s capability=%s outcome=%s",
            lease.activity_id,
            lease.task_id,
            lease.request_id,
            lease.capability,
            event_type,
        )


def _execution_request(lease: PublicationLease) -> PublicationExecutionRequest:
    return PublicationExecutionRequest(
        request_id=lease.request_id,
        capability=lease.capability,
        endpoint_id=lease.endpoint_id,
        operation=lease.operation,
        text=lease.text,
        source_audience_ref=lease.source_audience_ref,
        target_audience_ref=lease.target_audience_ref,
        root_message_id=lease.root_message_id,
        route_ref=lease.route_ref,
        destination=lease.destination,
        reason=lease.reason,
        source_endpoint_id=lease.source_endpoint_id,
        source_external_event_id=lease.source_external_event_id,
        hop_count=lease.hop_count,
        configuration_hash=lease.configuration_hash,
    )

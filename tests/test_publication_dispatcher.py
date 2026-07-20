from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from src.contracts.agent import CapabilityDescriptor, PublicationLease
from src.contracts.amp import AmpEnvelope
from src.localhost.ports import (
    PublicationExecutionRequest,
    PublicationExecutorBinding,
    PublicationOutcome,
)
from src.localhost.publication_dispatcher import PublicationDispatcher

CAPABILITY = "test.chat.reply"
ENDPOINT = "test.chat"
DESCRIPTOR = CapabilityDescriptor(
    CAPABILITY,
    "Reply",
    {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
    kind="publication",
    endpoint=ENDPOINT,
    operation="reply",
    root_only=True,
)


def _lease(request_id: str = "request") -> PublicationLease:
    return PublicationLease(
        activity_id="activity",
        task_id="task",
        agent_id="agent",
        request_id=request_id,
        capability=CAPABILITY,
        endpoint_id=ENDPOINT,
        operation="reply",
        text="hello",
        completion_mode="continue",
        source_audience_ref="test:owner",
        target_audience_ref="test:owner",
        root_message_id="root",
        route_ref="route",
    )


@dataclass(slots=True)
class _Queue:
    claims: tuple[PublicationLease, ...] = ()
    recoveries: tuple[PublicationLease, ...] = ()

    async def claim_publication_requests(self) -> tuple[PublicationLease, ...]:
        result, self.claims = self.claims, ()
        return result

    async def publication_recovery_requests(self) -> tuple[PublicationLease, ...]:
        result, self.recoveries = self.recoveries, ()
        return result


@dataclass(slots=True)
class _Ingress:
    values: list[object] = field(default_factory=list)

    async def submit_amp(self, value: object) -> str:
        self.values.append(value)
        return AmpEnvelope.parse(value).header.message_id


class _Executor:
    def __init__(self) -> None:
        self.requests: list[PublicationExecutionRequest] = []

    async def execute_publication(self, request: PublicationExecutionRequest) -> PublicationOutcome:
        self.requests.append(request)
        return PublicationOutcome("accepted", "accepted", external_message_id="external")

    async def recover_publication(self, request: PublicationExecutionRequest) -> PublicationOutcome:
        self.requests.append(request)
        return PublicationOutcome("delivery_unknown", "unknown", error="dispatch outcome unavailable")


def test_dispatcher_emits_deterministic_three_state_receipts_and_recovers_once() -> None:
    async def scenario() -> None:
        lease = _lease()
        queue = _Queue(claims=(lease,), recoveries=(lease,))
        ingress = _Ingress()
        executor = _Executor()
        dispatcher = PublicationDispatcher(queue, ingress)
        catalog = dispatcher.bind(
            (PublicationExecutorBinding(DESCRIPTOR, executor, executor, "platform.test", "instance"),)
        )

        assert catalog.capabilities == (DESCRIPTOR,)
        assert await dispatcher.recover_processing_publications() == 1
        assert await dispatcher.recover_processing_publications() == 0
        assert await dispatcher.dispatch_pending_publications() == 1

        recovery = AmpEnvelope.parse(ingress.values[0])
        accepted = AmpEnvelope.parse(ingress.values[1])
        assert recovery.payload.type == "publication.delivery_unknown"
        assert recovery.payload.data["error"] == "dispatch outcome unavailable"
        assert accepted.payload.type == "publication.succeeded"
        assert accepted.payload.data["result"] == {"external_message_id": "external"}
        assert recovery.header.message_id != accepted.header.message_id
        assert executor.requests[0].route_ref == "route"

        replay_ingress = _Ingress()
        replay = PublicationDispatcher(_Queue(claims=(lease,)), replay_ingress)
        replay.bind((PublicationExecutorBinding(DESCRIPTOR, executor, executor, "platform.test", "instance"),))
        await replay.dispatch_pending_publications()
        replayed = AmpEnvelope.parse(replay_ingress.values[0])
        assert replayed.header.message_id == accepted.header.message_id

    asyncio.run(scenario())


def test_dispatcher_turns_an_unavailable_executor_into_a_failed_receipt() -> None:
    async def scenario() -> None:
        ingress = _Ingress()
        dispatcher = PublicationDispatcher(_Queue(claims=(_lease("unavailable"),)), ingress)
        dispatcher.bind(())

        assert await dispatcher.dispatch_pending_publications() == 1
        receipt = AmpEnvelope.parse(ingress.values[0])
        assert receipt.payload.type == "publication.failed"
        assert receipt.payload.data["error"] == f"unavailable Publication capability: {CAPABILITY}"

    asyncio.run(scenario())

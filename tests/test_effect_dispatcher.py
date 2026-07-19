from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import pytest

from src.contracts.agent import CapabilityDescriptor, EffectLease
from src.contracts.amp import AmpEnvelope
from src.localhost.effect_dispatcher import EffectBindingError, EffectDispatcher
from src.localhost.ports import EffectExecutionRequest, EffectExecutorBinding, EffectOutcome


def _lease(capability: str = "test.echo") -> EffectLease:
    return EffectLease(
        activity_id="activity",
        task_id="task",
        agent_id="agent",
        request_id="request",
        session_id="session",
        capability=capability,
        parameters={"text": "hello"},
    )


@dataclass(slots=True)
class _Queue:
    leases: tuple[EffectLease, ...]
    claims: int = 0

    async def claim_effect_requests(self) -> tuple[EffectLease, ...]:
        self.claims += 1
        leases, self.leases = self.leases, ()
        return leases


@dataclass(slots=True)
class _Ingress:
    values: list[object] = field(default_factory=list)

    async def submit_amp(self, value: object) -> str:
        self.values.append(value)
        return AmpEnvelope.parse(value).header.message_id


class _FailingIngress:
    async def submit_amp(self, _value: object) -> str:
        message = "inbox unavailable"
        raise OSError(message)


class _Executor:
    async def execute_effect(self, request: EffectExecutionRequest) -> EffectOutcome:
        return EffectOutcome(succeeded=True, summary="echoed", result={"text": request.parameters["text"]})


def _binding(capability: str = "test.echo") -> EffectExecutorBinding:
    descriptor = CapabilityDescriptor(capability, "echo", {"type": "object"})
    return EffectExecutorBinding(descriptor, _Executor(), "platform.test", "test")


def test_dispatcher_binds_catalog_once_and_rejects_duplicate_capabilities() -> None:
    dispatcher = EffectDispatcher(_Queue(()), _Ingress())

    with pytest.raises(EffectBindingError, match="duplicate active"):
        dispatcher.bind((_binding(), _binding()))

    dispatcher = EffectDispatcher(_Queue(()), _Ingress())
    catalog = dispatcher.bind(())
    assert catalog.capabilities == ()
    with pytest.raises(EffectBindingError, match="already bound"):
        dispatcher.bind(())


def test_headless_dispatcher_deterministically_fails_an_unavailable_persisted_effect() -> None:
    async def scenario() -> None:
        ingress = _Ingress()
        dispatcher = EffectDispatcher(_Queue((_lease("test.unavailable"),)), ingress)
        dispatcher.bind(())

        assert await dispatcher.dispatch_pending_effects() == 1
        receipt = AmpEnvelope.parse(ingress.values[0])
        assert receipt.payload.type == "effect.failed"
        assert receipt.payload.data["error"] == "unavailable effect capability: test.unavailable"

    asyncio.run(scenario())


def test_receipt_ingress_failure_propagates_to_dispatch_caller() -> None:
    async def scenario() -> None:
        dispatcher = EffectDispatcher(_Queue((_lease(),)), _FailingIngress())
        dispatcher.bind((_binding(),))

        with pytest.raises(OSError, match="inbox unavailable"):
            await dispatcher.dispatch_pending_effects()

    asyncio.run(scenario())

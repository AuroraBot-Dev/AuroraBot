from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import pytest

from src.contracts.agent import CapabilityDescriptor, ToolLease
from src.contracts.tool import ToolExecutionRequest, ToolExecutorBinding, ToolOutcome, ToolOutcomeStatus
from src.engine.tool_registry import ToolBindingError, ToolRegistry


def _lease(capability: str = "test.echo") -> ToolLease:
    return ToolLease("activity", "task", "agent", "request", "session", capability, {"text": "hello"})


@dataclass(slots=True)
class _Queue:
    claims: tuple[ToolLease, ...] = ()
    recoveries: tuple[ToolLease, ...] = ()

    async def claim_tool_requests(self) -> tuple[ToolLease, ...]:
        leases, self.claims = self.claims, ()
        return leases

    async def tool_recovery_requests(self) -> tuple[ToolLease, ...]:
        leases, self.recoveries = self.recoveries, ()
        return leases


@dataclass(slots=True)
class _Completion:
    values: list[dict[str, object]] = field(default_factory=list)

    async def complete_tool(self, **value: object) -> None:
        self.values.append(value)


class _Executor:
    async def execute_tool(self, request: ToolExecutionRequest) -> ToolOutcome:
        return ToolOutcome(ToolOutcomeStatus.SUCCEEDED, "echoed", result={"text": request.parameters["text"]})

    async def recover_tool(self, request: ToolExecutionRequest) -> ToolOutcome:
        return await self.execute_tool(request)


def _binding(capability: str = "test.echo", *, recovery: object | None = None) -> ToolExecutorBinding:
    descriptor = CapabilityDescriptor(capability, "echo", {"type": "object"})
    return ToolExecutorBinding(descriptor, _Executor(), "platform.test", "test", recovery)  # type: ignore[arg-type]


def test_registry_requires_one_flat_binding_catalog() -> None:
    registry = ToolRegistry(_Queue(), _Completion())
    with pytest.raises(ToolBindingError, match="not been bound"):
        asyncio.run(registry.execute_pending())
    with pytest.raises(ToolBindingError, match="duplicate active"):
        registry.bind((_binding(), _binding()))


def test_dispatch_and_recovery_emit_three_state_tool_receipts() -> None:
    async def scenario() -> None:
        completion = _Completion()
        queue = _Queue(claims=(_lease(),), recoveries=(_lease("test.no-recovery"),))
        registry = ToolRegistry(queue, completion)
        registry.bind((_binding(),))
        assert await registry.execute_pending() == 1
        assert await registry.recover_pending() == 1
        assert [item["status"] for item in completion.values] == ["succeeded", "unknown"]

    asyncio.run(scenario())


def test_executor_exception_is_unknown_and_missing_executor_is_failed() -> None:
    class FailingExecutor:
        async def execute_tool(self, request: ToolExecutionRequest) -> ToolOutcome:
            _ = request
            raise TimeoutError("result lost")

    async def scenario() -> None:
        completion = _Completion()
        queue = _Queue(claims=(_lease(), _lease("missing")))
        registry = ToolRegistry(queue, completion)
        descriptor = CapabilityDescriptor("test.echo", "echo", {"type": "object"})
        registry.bind((ToolExecutorBinding(descriptor, FailingExecutor(), "test", "test"),))
        await registry.execute_pending()
        assert [item["status"] for item in completion.values] == ["unknown", "failed"]

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "arguments",
    (
        ("invalid", "summary", None, None),
        ("succeeded", "summary", None, "unexpected"),
        ("failed", "summary", {}, "failed"),
    ),
)
def test_tool_outcome_rejects_invalid_shapes(arguments: tuple[object, ...]) -> None:
    with pytest.raises(ValueError):
        ToolOutcome(*arguments)  # type: ignore[arg-type]

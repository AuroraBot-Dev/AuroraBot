from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import pytest

from src.contracts.agent import CapabilityDescriptor, ToolLease
from src.localhost.ports import ToolExecutionRequest, ToolExecutorBinding, ToolOutcome
from src.localhost.tool_dispatcher import ToolBindingError, ToolDispatcher


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
        return ToolOutcome("succeeded", "echoed", result={"text": request.parameters["text"]})


def _binding(capability: str = "test.echo", *, recovery: object | None = None) -> ToolExecutorBinding:
    descriptor = CapabilityDescriptor(capability, "echo", {"type": "object"})
    return ToolExecutorBinding(descriptor, _Executor(), "platform.test", "test", recovery)  # type: ignore[arg-type]


def test_dispatcher_binds_one_flat_catalog() -> None:
    dispatcher = ToolDispatcher(_Queue(), _Completion())
    with pytest.raises(ToolBindingError, match="duplicate active"):
        dispatcher.bind((_binding(), _binding()))


def test_dispatch_and_recovery_emit_three_state_tool_receipts() -> None:
    async def scenario() -> None:
        completion = _Completion()
        queue = _Queue(claims=(_lease(),), recoveries=(_lease("test.no-recovery"),))
        dispatcher = ToolDispatcher(queue, completion)
        dispatcher.bind((_binding(),))
        assert await dispatcher.dispatch_pending_tools() == 1
        assert await dispatcher.recover_processing_tools() == 1
        assert [item["status"] for item in completion.values] == ["succeeded", "unknown"]

    asyncio.run(scenario())


def test_executor_exception_is_unknown_not_retried() -> None:
    class FailingExecutor:
        async def execute_tool(self, _request: ToolExecutionRequest) -> ToolOutcome:
            message = "result lost"
            raise TimeoutError(message)

    async def scenario() -> None:
        completion = _Completion()
        dispatcher = ToolDispatcher(_Queue(claims=(_lease(),)), completion)
        descriptor = CapabilityDescriptor("test.echo", "echo", {"type": "object"})
        dispatcher.bind((ToolExecutorBinding(descriptor, FailingExecutor(), "test", "test"),))
        await dispatcher.dispatch_pending_tools()
        assert completion.values[0]["status"] == "unknown"

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "arguments",
    [
        ("invalid", "summary", None, None),
        ("succeeded", "summary", None, "unexpected"),
        ("failed", "summary", {}, "failed"),
    ],
)
def test_tool_outcome_rejects_invalid_shapes(arguments: tuple[object, ...]) -> None:
    with pytest.raises(ValueError):
        ToolOutcome(*arguments)  # type: ignore[arg-type]

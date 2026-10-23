from __future__ import annotations

import asyncio
import json
from io import StringIO
from typing import TYPE_CHECKING, Any

import pytest

from playground.modules.agent.fixtures import DemoModel, EchoTool
from playground.session import Session
from playground.terminal import interact

if TYPE_CHECKING:
    from aurora_agent import ModelRequest, ModelResponse, ToolCall, ToolContext, ToolOutput


def call(session: Session, operation: str, **inputs: Any) -> dict[str, Any]:
    return session.handle(json.dumps({"module": "agent", "operation": operation, "input": inputs}))


def test_agent_steps_preserve_queued_input_and_session_isolation() -> None:
    with Session() as session, Session() as other:
        assert call(session, "create")["result"]["status"] == "ready"
        assert call(session, "step")["result"]["calls"][0]["status"] == "pending"
        assert call(session, "append", message="补充条件")["result"]["queued_messages"] == ["补充条件"]
        first = call(session, "step")["result"]
        assert first["queued_messages"] == ["补充条件"]
        assert [record["status"] for record in first["calls"]] == ["succeeded", "pending"]
        assert call(session, "create")["error"]["code"] == "execution_error"
        assert call(session, "snapshot")["result"] == first
        assert call(other, "snapshot")["error"]["code"] == "execution_error"
        assert call(other, "create")["result"]["status"] == "ready"
        final = call(session, "run")["result"]
        assert final["status"] == "completed"
        assert final["queued_messages"] == []
        assert [message["role"] for message in final["messages"]] == [
            "message",
            "assistant",
            "tool",
            "tool",
            "message",
            "assistant",
        ]
        assert "补充条件" in final["result"]["output"]
        assert call(other, "snapshot")["result"]["stats"]["model_calls"] == 0
        assert call(session, "create", run_id="another")["result"]["status"] == "ready"
        assert call(session, "snapshot")["result"] == final


def test_async_operations_share_one_loop_and_close_it(monkeypatch: pytest.MonkeyPatch) -> None:
    loops: list[asyncio.AbstractEventLoop] = []
    complete = DemoModel.complete
    execute = EchoTool.execute

    async def model(self: DemoModel, request: ModelRequest) -> ModelResponse:
        loops.append(asyncio.get_running_loop())
        return await complete(self, request)

    async def tool(self: EchoTool, call: ToolCall, context: ToolContext) -> ToolOutput:
        loops.append(asyncio.get_running_loop())
        return await execute(self, call, context)

    monkeypatch.setattr(DemoModel, "complete", model)
    monkeypatch.setattr(EchoTool, "execute", tool)
    with Session() as session:
        call(session, "create")
        call(session, "step")
        call(session, "step")
        assert session.handle('{"module":"kernel","operation":"increment"}')["ok"]
        assert call(session, "run")["result"]["status"] == "completed"
        assert loops and all(loop is loops[0] for loop in loops)
        assert not loops[0].is_closed()
    assert loops[0].is_closed()
    assert call(session, "snapshot")["error"]["code"] == "session_closed"


def test_describe_and_invalid_input_do_not_allocate_a_runner(monkeypatch: pytest.MonkeyPatch) -> None:
    created: list[asyncio.Runner] = []
    original = asyncio.Runner

    def tracked_runner() -> asyncio.Runner:
        runner = original()
        created.append(runner)
        return runner

    monkeypatch.setattr(asyncio, "Runner", tracked_runner)
    with Session() as session:
        assert session.handle('{"action":"list"}')["ok"]
        assert session.handle('{"action":"describe","module":"agent"}')["ok"]
        for inputs in ({"message": " "}, {"max_model_calls": True}, {"unknown": 1}, {"scenario": "bad"}):
            assert call(session, "create", **inputs)["error"]["code"] == "invalid_input"
        assert not created
        assert call(session, "create")["ok"]
        before = call(session, "snapshot")["result"]
        assert call(session, "append", message=" ")["error"]["code"] == "invalid_input"
        assert call(session, "snapshot")["result"] == before
        assert len(created) == 1


@pytest.mark.parametrize(
    ("scenario", "status", "tool_calls"),
    [("answer", "completed", 0), ("policy", "completed", 0), ("unknown", "failed", 1)],
)
def test_terminal_runs_are_observable_without_replaying_effects(scenario: str, status: str, tool_calls: int) -> None:
    with Session() as session:
        assert call(session, "create", scenario=scenario)["ok"]
        final = call(session, "run")["result"]
        assert final["status"] == status
        assert final["stats"]["tool_calls"] == tool_calls
        if scenario == "unknown":
            assert final["calls"][0]["status"] == "unknown"
        assert call(session, "run")["result"] == final
        assert call(session, "append", message="终态输入")["error"]["code"] == "execution_error"


def test_cancel_at_step_boundary_and_limit_preserve_pending_calls() -> None:
    with Session() as session:
        call(session, "create")
        call(session, "step")
        cancelled = call(session, "cancel")["result"]
        assert cancelled["status"] == "cancelled"
        assert cancelled["stats"]["tool_calls"] == 0
        assert all(record["status"] == "pending" for record in cancelled["calls"])
        assert call(session, "run")["result"] == cancelled
        call(session, "create", run_id="limited", max_tool_calls=0)
        limited = call(session, "run", run_id="limited")["result"]
        assert limited["status"] == "limit_reached"
        assert limited["stats"]["tool_calls"] == 0


def test_agent_pipe_emits_only_json_responses(capsys: pytest.CaptureFixture[str]) -> None:
    requests = [
        {"module": "agent", "operation": "create"},
        {"module": "agent", "operation": "step"},
        {"module": "agent", "operation": "append", "input": {"message": "补充"}},
        {"module": "agent", "operation": "run"},
        {"module": "agent", "operation": "append", "input": {"message": "已结束"}},
        {"module": "agent", "operation": "snapshot"},
        {"action": "exit"},
    ]
    stdout, stderr = StringIO(), StringIO()
    assert interact(StringIO("\n".join(json.dumps(item) for item in requests)), stdout, stderr, pretty=False) == 0
    responses = [json.loads(line) for line in stdout.getvalue().splitlines()]
    assert len(responses) == len(requests)
    assert responses[3]["result"]["status"] == "completed"
    assert responses[4]["error"]["code"] == "execution_error"
    assert responses[5]["result"] == responses[3]["result"]
    assert stderr.getvalue() == ""
    captured = capsys.readouterr()
    assert captured.out == captured.err == ""


@pytest.mark.parametrize("ending", ["eof", "exit", "interrupt"])
def test_interact_closes_async_resources_on_every_exit(ending: str, monkeypatch: pytest.MonkeyPatch) -> None:
    loops: list[asyncio.AbstractEventLoop] = []
    finalized: list[bool] = []
    complete = DemoModel.complete

    async def resource(ready: asyncio.Event) -> None:
        try:
            ready.set()
            await asyncio.Event().wait()
        finally:
            finalized.append(True)

    async def model(self: DemoModel, request: ModelRequest) -> ModelResponse:
        loops.append(asyncio.get_running_loop())
        ready = asyncio.Event()
        task = asyncio.create_task(resource(ready))
        await ready.wait()
        assert not task.done()
        return await complete(self, request)

    class InterruptedInput(StringIO):
        def readline(self, size: int = -1) -> str:
            line = super().readline(size)
            if not line:
                raise KeyboardInterrupt
            return line

    monkeypatch.setattr(DemoModel, "complete", model)
    lines = '{"module":"agent","operation":"create"}\n{"module":"agent","operation":"step"}\n'
    if ending == "exit":
        lines += '{"action":"exit"}\n'
    stdin = InterruptedInput(lines) if ending == "interrupt" else StringIO(lines)
    expected_code = 130 if ending == "interrupt" else 0
    assert interact(stdin, StringIO(), StringIO()) == expected_code
    assert finalized == [True]
    assert all(loop.is_closed() for loop in loops)

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from aurora_agent import RunSnapshot, ToolExecutionError
from aurora_bot.contracts import (
    ChatMessage,
    CognitionRequest,
    ToolCall,
    ToolOutput,
    ToolStatus,
    WorldFrontier,
)
from aurora_bot.contracts.process import CognitionProcess
from aurora_bot.world import SqlAlchemyWorldJournal
from aurora_kernel import Context, namespace
from tests.engine.support import RecordingTool
from tests.support.engine import make_engine
from tests.support.model import ScriptedModel
from tests.support.prompt import _agent

if TYPE_CHECKING:
    from pathlib import Path


def request(run_id: str = "run") -> CognitionRequest:
    return CognitionRequest("检查", agent=_agent().definition_id, run_id=run_id)


def test_independent_run_preserves_model_identity_results_and_world_causality(tmp_path: Path) -> None:
    async def scenario() -> None:
        world = SqlAlchemyWorldJournal(tmp_path / "world.sqlite3")
        tool = RecordingTool()
        profile = replace(_agent(), tools=frozenset({tool.definition.name}))
        model = ScriptedModel(
            [
                ChatMessage.assistant(tool_calls=(ToolCall("call", tool.definition.name, {"value": "已完成"}),)),
                ChatMessage.assistant("答复"),
            ]
        )
        engine = make_engine(model, (profile,), world=world, tools=(tool,))
        snapshots: list[RunSnapshot] = []
        try:
            result = await engine.execute(request(), observer=snapshots.append)
            assert result.status == "completed" and result.output == "答复"
            assert [message.role for message in snapshots[-1].messages] == ["message", "assistant", "tool", "assistant"]
            assert model.requests[0].model == profile.model
            assert len(tool.calls) == 1
            assert tool.calls[0].context is not None
            assert tool.calls[0].context.run_id == "run"
            assert tool.calls[0].context.caused_by == "run:tool:call:requested"
            started = await world.commit("run:run:started")
            output = await world.commit("run:tool:call:result")
            assert started is not None and started.data["instance"]["instance_id"] == "run"
            assert output is not None and "test:world/output" in output.scopes
            with pytest.raises(ValueError, match="已存在"):
                await engine.execute(request())
            assert len(tool.calls) == 1
        finally:
            await world.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("status", [ToolStatus.FAILED, ToolStatus.UNKNOWN])
def test_tool_outcomes_are_persisted_without_replay(tmp_path: Path, status: ToolStatus) -> None:
    async def scenario() -> None:
        world = SqlAlchemyWorldJournal(tmp_path / "world.sqlite3")
        tool = RecordingTool(status)
        profile = replace(_agent(), tools=frozenset({tool.definition.name}))
        model = ScriptedModel(
            [
                ChatMessage.assistant(tool_calls=(ToolCall("call", tool.definition.name, {"value": "核对结果"}),)),
                ChatMessage.assistant("已知悉"),
            ]
        )
        engine = make_engine(model, (profile,), world=world, tools=(tool,))
        try:
            result = await engine.execute(request())
            assert len(tool.calls) == 1
            commit = await world.commit("run:tool:call:result")
            assert commit is not None and commit.kind == f"tool.{status.value}"
            assert result.status == ("failed" if status is ToolStatus.UNKNOWN else "completed")
            assert len(model.requests) == (1 if status is ToolStatus.UNKNOWN else 2)
        finally:
            await world.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("explicit", [False, True])
def test_tool_exception_distinguishes_failure_from_unknown_effect(tmp_path: Path, explicit: bool) -> None:
    class BrokenTool(RecordingTool):
        async def execute(self, call: ToolCall) -> ToolOutput:
            self.calls.append(call)
            if explicit:
                raise ToolExecutionError("明确未成功")
            raise RuntimeError("执行结果不确定")

    async def scenario() -> None:
        world = SqlAlchemyWorldJournal(tmp_path / "world.sqlite3")
        tool = BrokenTool()
        profile = replace(_agent(), tools=frozenset({tool.definition.name}))
        model = ScriptedModel(
            [
                ChatMessage.assistant(tool_calls=(ToolCall("call", tool.definition.name, {"value": "值"}),)),
                ChatMessage.assistant("已知悉"),
            ]
        )
        engine = make_engine(model, (profile,), world=world, tools=(tool,))
        try:
            if explicit:
                assert (await engine.execute(request())).status == "completed"
            else:
                with pytest.raises(RuntimeError, match="不确定"):
                    await engine.execute(request())
            committed = await world.commit("run:tool:call:result")
            assert committed is not None and committed.kind == ("tool.failed" if explicit else "tool.unknown")
            assert len(tool.calls) == 1
        finally:
            await world.close()

    asyncio.run(scenario())


def test_world_update_reconsiders_the_entire_batch_before_effects(tmp_path: Path) -> None:
    async def scenario() -> None:
        world = SqlAlchemyWorldJournal(tmp_path / "world.sqlite3")
        await world.initialize()
        await world.append_commit(
            commit_id="input",
            kind="environment.message",
            source="test",
            summary="新消息",
            scopes=frozenset({"test:world/input"}),
            based_on=WorldFrontier(),
            occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
            data={},
        )
        tool = RecordingTool()
        profile = replace(_agent(), tools=frozenset({tool.definition.name}))
        model = ScriptedModel(
            [
                ChatMessage.assistant(
                    tool_calls=(
                        ToolCall("a", tool.definition.name, {"value": "a"}),
                        ToolCall("b", tool.definition.name, {"value": "b"}),
                    )
                ),
                ChatMessage.assistant(tool_calls=(ToolCall("c", tool.definition.name, {"value": "c"}),)),
                ChatMessage.assistant("完成"),
            ]
        )
        engine = make_engine(model, (profile,), world=world, tools=(tool,))
        try:
            result = await engine.execute(request())
            assert result.status == "completed"
            assert [call.call_id for call in tool.calls] == ["c"]
            assert [message.tool_call_id for message in model.requests[1].messages if message.role == "tool"] == [
                "a",
                "b",
            ]
            assert "world.delta" in model.requests[1].messages[-1].content
            assert await world.commit("run:tool:a:requested") is None
            assert await world.commit("run:tool:c:requested") is not None
        finally:
            await world.close()

    asyncio.run(scenario())


def test_custom_model_hook_is_invoked_and_cannot_bypass_tool_limit(tmp_path: Path) -> None:
    @namespace("custom")
    def custom(ctx: Context) -> None:
        ctx["custom"]["calls"] = 0

    tool = RecordingTool()

    @custom.hook("aurora:kernel/module/ai:complete", priority=10)
    async def complete(ctx: Context, model_request: object) -> ChatMessage:
        ctx["custom"]["calls"] += 1
        return ChatMessage.assistant(tool_calls=(ToolCall("call", tool.definition.name, {"value": "不能执行"}),))

    async def scenario() -> None:
        world = SqlAlchemyWorldJournal(tmp_path / "world.sqlite3")
        profile = replace(_agent(), tools=frozenset({tool.definition.name}))
        model = ScriptedModel([])
        engine = make_engine(
            model,
            (profile,),
            world=world,
            tools=(tool,),
            extensions=(custom,),
            process=CognitionProcess(max_tool_calls=0),
        )
        try:
            result = await engine.execute(request())
            assert result.status == "limit_reached"
            assert not tool.calls and not model.requests
        finally:
            await world.close()

    asyncio.run(scenario())

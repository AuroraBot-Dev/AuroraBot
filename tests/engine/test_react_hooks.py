from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import TYPE_CHECKING

import pytest

from aurora_bot.contracts import ChatMessage, CognitionRequest, ToolCall, ToolOutput
from aurora_bot.world import SqlAlchemyWorldJournal
from aurora_kernel import Context, namespace
from tests.engine.support import RecordingTool
from tests.support.engine import make_engine
from tests.support.model import ScriptedModel
from tests.support.prompt import _agent

if TYPE_CHECKING:
    from pathlib import Path

    from aurora_agent import RunSnapshot


def test_post_tool_hook_failure_preserves_confirmed_result(tmp_path: Path) -> None:
    @namespace("observer")
    def observer(ctx: Context) -> None:
        pass

    @observer.hook("aurora:kernel/module/engine:after_tool")
    def after_tool(ctx: Context, run_id: str, call: ToolCall, output: ToolOutput) -> None:
        raise RuntimeError("观察失败")

    async def scenario() -> None:
        world = SqlAlchemyWorldJournal(tmp_path / "world.sqlite3")
        tool = RecordingTool()
        definition = replace(_agent(), tools=frozenset({tool.definition.name}))
        model = ScriptedModel(
            [ChatMessage.assistant(tool_calls=(ToolCall("call", tool.definition.name, {"value": "确定结果"}),))]
        )
        engine = make_engine(model, (definition,), world=world, tools=(tool,), extensions=(observer,))
        request = CognitionRequest("检查", agent=definition.definition_id, run_id="run")
        try:
            with pytest.raises(RuntimeError, match="观察失败"):
                await engine.execute(request)
            committed = await world.commit("run:tool:call:result")
            assert committed is not None and committed.kind == "tool.succeeded"
            with pytest.raises(ValueError, match="已存在"):
                await engine.execute(request)
            assert len(tool.calls) == 1
        finally:
            await world.close()

    asyncio.run(scenario())


def test_step_hooks_receive_isolated_run_snapshots(tmp_path: Path) -> None:
    seen: list[RunSnapshot] = []

    @namespace("trace")
    def trace(ctx: Context) -> None:
        pass

    @trace.hook("aurora:kernel/module/engine:after_step")
    def after_step(ctx: Context, snapshot: RunSnapshot) -> None:
        seen.append(snapshot)

    async def scenario() -> None:
        world = SqlAlchemyWorldJournal(tmp_path / "world.sqlite3")
        definition = _agent()
        engine = make_engine(
            ScriptedModel([ChatMessage.assistant("甲"), ChatMessage.assistant("乙")]),
            (definition,),
            world=world,
            extensions=(trace,),
        )
        try:
            for run_id in ("first", "second"):
                await engine.execute(CognitionRequest(run_id, agent=definition.definition_id, run_id=run_id))
            assert [snapshot.run_id for snapshot in seen] == ["first", "second"]
            assert [snapshot.messages[0].content for snapshot in seen] == ["first", "second"]
        finally:
            await world.close()

    asyncio.run(scenario())

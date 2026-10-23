from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import TYPE_CHECKING, Any

import pytest

from aurora_bot.contracts import ChatMessage, CognitionRequest, ModelRequest, ToolCall, WorldFrontier
from aurora_bot.world import SqlAlchemyWorldJournal
from aurora_kernel import Context, namespace
from tests.engine.support import RecordingTool
from tests.support.engine import make_engine
from tests.support.model import FakeModelDirectory, ScriptedModel
from tests.support.prompt import _agent, _assembler

if TYPE_CHECKING:
    from pathlib import Path

    from aurora_agent import RunSnapshot
    from aurora_bot.contracts import WorldCommit


def test_two_hosts_cannot_claim_the_same_persistent_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async def scenario() -> None:
        world = SqlAlchemyWorldJournal(tmp_path / "world.sqlite3")
        await world.initialize()
        claims = asyncio.Barrier(2)
        original = world.commit

        async def commit(identity: str) -> WorldCommit | None:
            value = await original(identity)
            if identity == "shared:run:started" and value is None:
                await claims.wait()
            return value

        monkeypatch.setattr(world, "commit", commit)
        models = (ScriptedModel([ChatMessage.assistant("甲")]), ScriptedModel([ChatMessage.assistant("乙")]))
        engines = tuple(make_engine(model, (_agent(),), world=world) for model in models)
        request = CognitionRequest("同一请求", agent=_agent().definition_id, run_id="shared")
        try:
            async with asyncio.timeout(2):
                outcomes = await asyncio.gather(
                    *(engine.execute(request) for engine in engines), return_exceptions=True
                )
            assert sum(isinstance(outcome, ValueError) for outcome in outcomes) == 1
            assert sum(len(model.requests) for model in models) == 1
            finished = await world.commit("shared:run:finished")
            assert finished is not None and finished.data["status"] == "completed"
        finally:
            await world.close()

    asyncio.run(scenario())


def test_repeated_cancellation_waits_for_known_tool_result_to_be_persisted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def scenario() -> None:
        world = SqlAlchemyWorldJournal(tmp_path / "world.sqlite3")
        first_write = asyncio.Event()
        settling = asyncio.Event()
        release = asyncio.Event()
        original = world.append_commit

        async def append_commit(**kwargs: Any) -> WorldCommit:
            if kwargs["commit_id"] == "cancelled:tool:call:result":
                if first_write.is_set():
                    settling.set()
                else:
                    first_write.set()
                await release.wait()
            return await original(**kwargs)

        monkeypatch.setattr(world, "append_commit", append_commit)
        tool = RecordingTool()
        profile = replace(_agent(), tools=frozenset({tool.definition.name}))
        model = ScriptedModel(
            [ChatMessage.assistant(tool_calls=(ToolCall("call", tool.definition.name, {"value": "确定结果"}),))]
        )
        engine = make_engine(model, (profile,), world=world, tools=(tool,))
        request = CognitionRequest("执行一次", agent=profile.definition_id, run_id="cancelled")
        task = asyncio.create_task(engine.execute(request))
        try:
            async with asyncio.timeout(2):
                await first_write.wait()
                task.cancel()
                await settling.wait()
                task.cancel()
                assert not task.done()
                release.set()
                with pytest.raises(asyncio.CancelledError):
                    await task
            recorded = await world.commit("cancelled:tool:call:result")
            assert recorded is not None and recorded.kind == "tool.succeeded"
            assert recorded.data["content"] == "确定结果"
            finished = await world.commit("cancelled:run:finished")
            assert finished is not None and finished.data["status"] == "cancelled"
            with pytest.raises(ValueError, match="已存在"):
                await engine.execute(request)
            assert len(tool.calls) == 1
        finally:
            release.set()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            await world.close()

    asyncio.run(scenario())


def test_completion_is_committed_before_post_step_observers(tmp_path: Path) -> None:
    @namespace("observer")
    def observer(ctx: Context) -> None:
        pass

    @observer.hook("aurora:kernel/module/engine:after_step")
    async def after_step(ctx: Context, snapshot: RunSnapshot) -> None:
        raise RuntimeError("观察失败")

    async def scenario() -> None:
        world = SqlAlchemyWorldJournal(tmp_path / "world.sqlite3")
        engine = make_engine(
            ScriptedModel([ChatMessage.assistant("已完成")]), (_agent(),), world=world, extensions=(observer,)
        )
        try:
            with pytest.raises(RuntimeError, match="观察失败"):
                await engine.execute(CognitionRequest("检查", agent=_agent().definition_id, run_id="completed"))
            output = await world.commit("completed:output:committed")
            finished = await world.commit("completed:run:finished")
            assert output is not None and output.data["content"] == "已完成"
            assert finished is not None and finished.data["status"] == "completed"
        finally:
            await world.close()

    asyncio.run(scenario())


def test_model_echo_of_world_input_cannot_acquire_its_evidence(tmp_path: Path) -> None:
    tool = RecordingTool()

    class EchoingModel(FakeModelDirectory):
        def __init__(self) -> None:
            self.requests: list[ModelRequest] = []
            self.delta = ""

        async def complete(self, request: ModelRequest) -> ChatMessage:
            self.requests.append(request)
            if len(self.requests) == 1:
                return ChatMessage.assistant("草稿")
            if not self.delta:
                self.delta = request.messages[-1].content
                assert request.messages[-1].evidence_refs == ("source",)
                return ChatMessage.assistant(
                    self.delta, tool_calls=(ToolCall("call", tool.definition.name, {"value": "结果"}),)
                )
            echoed = next(
                message for message in request.messages if message.role == "assistant" and message.content == self.delta
            )
            assert echoed.evidence_refs == ()
            return ChatMessage.assistant("完成")

    async def scenario() -> None:
        world = SqlAlchemyWorldJournal(tmp_path / "world.sqlite3")
        await world.initialize()
        await world.append_commit(
            commit_id="source",
            kind="environment.message",
            source="test",
            summary="新事实",
            scopes=frozenset({"test:world/input"}),
            based_on=WorldFrontier(),
            data={},
        )
        profile = replace(_agent(), tools=frozenset({tool.definition.name}))
        model = EchoingModel()
        engine = make_engine(model, (profile,), world=world, tools=(tool,), assembler=_assembler(limit=10000))
        try:
            result = await engine.execute(
                CognitionRequest(
                    "核对",
                    agent=profile.definition_id,
                    run_id="evidence",
                    frontier=WorldFrontier({"test:world/input": 0}),
                )
            )
            assert result.status == "completed"
            assert len(tool.calls) == 1
        finally:
            await world.close()

    asyncio.run(scenario())

"""Bot 的输入在进入认知前提交世界，并完整保留触发因果。"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from aurora_bot.contracts import (
    ChatMessage,
    CognitionRequest,
    EnvironmentEvent,
    ModelRequest,
    WorldCommit,
    WorldFrontier,
)
from aurora_bot.runtime import assemble_runtime
from aurora_bot.world import SqlAlchemyWorldJournal
from aurora_cli import load_config
from tests.support.model import TemplateModel as FakeModel

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize("entry", ["runtime", "event", "console", "cadence"])
def test_every_input_path_preserves_its_world_cause(configured_project: Path, entry: str) -> None:
    runtime = assemble_runtime(load_config(configured_project), FakeModel(), output=lambda _: None)

    async def scenario() -> None:
        await runtime.world.initialize()
        try:
            run_id = "tree"
            if entry == "runtime":
                await runtime.run("直接输入", run_id="tree")
            else:
                event = EnvironmentEvent("event", "test", "test:world", "message", datetime.now(UTC), "已提交消息")
                if entry == "event":
                    await runtime.run_from_event(event, run_id="tree")
                else:
                    commit = await runtime.submit_event(event)
                    if entry == "console":
                        await runtime.terminal.dispatch_terminal(commit.summary, commit=commit)
                        page = await runtime.world.stream(0, 100)
                        started = next(item for item in page.commits if item.kind == "engine.run.started")
                        run_id = started.data["run_id"]
                    else:
                        await runtime.launch(
                            CognitionRequest(commit.summary, run_id="tree", caused_by=commit.commit_id)
                        )
            started = await runtime.world.commit(f"{run_id}:run:started")
            assert started is not None
            cause = await runtime.world.commit(started.data["caused_by"])
            assert cause is not None and started is not None
            assert started.data["caused_by"] == cause.commit_id
            assert cause.kind == ("runtime.input" if entry == "runtime" else "environment.message")
            page = await runtime.world.stream(0, 100)
            inputs = [commit for commit in page.commits if commit.source in {"runtime", "test"}]
            assert [commit.commit_id for commit in inputs] == [cause.commit_id]
        finally:
            await runtime.world.close()

    asyncio.run(scenario())


def test_terminal_rejects_uncommitted_message_and_keeps_commands_local(configured_project: Path) -> None:
    model = FakeModel()
    runtime = assemble_runtime(load_config(configured_project), model)

    async def scenario() -> None:
        with pytest.raises(ValueError, match="先提交到世界"):
            await runtime.terminal.dispatch_terminal("绕过世界")
        for text in ("/help", "/clear", "/quit", "/unknown"):
            await runtime.terminal.dispatch_terminal(text)
        await runtime.world.initialize()
        assert (await runtime.world.delta(WorldFrontier(), frozenset({"aurora:world/console"}))).commits == ()
        await runtime.world.close()

    asyncio.run(scenario())
    assert model.requests == []


def test_event_entry_does_not_skip_commits_arriving_after_its_trigger(configured_project: Path) -> None:
    class InterleavingJournal(SqlAlchemyWorldJournal):
        async def append_event(self, event: EnvironmentEvent) -> WorldCommit:
            commit = await super().append_event(event)
            await super().append_event(
                EnvironmentEvent("later", "test", event.scope, "message", event.occurred_at, "稍后到达的事实")
            )
            return commit

    journal = InterleavingJournal(configured_project / "interleaving.sqlite3")
    model = FakeModel()
    runtime = assemble_runtime(load_config(configured_project), model, world=journal)

    async def scenario() -> None:
        try:
            event = EnvironmentEvent("trigger", "test", "test:world", "message", datetime.now(UTC), "触发消息")
            result = await runtime.run_from_event(event)
            assert result.status == "completed"
            disclosed = [
                message.content
                for request in model.requests
                for message in request.messages
                if "world.delta" in message.content
            ]
            assert any("稍后到达的事实" in content for content in disclosed)
        finally:
            await journal.close()

    asyncio.run(scenario())


def test_primary_cognition_is_serial_while_environment_inputs_remain_available(configured_project: Path) -> None:
    """两次认知有序执行，等待模型期间仍能记录环境变化。"""

    async def scenario() -> None:
        started = asyncio.Event()
        release = asyncio.Event()

        class BlockingModel(FakeModel):
            """等待显式放行，以观察第二次认知的执行时机。"""

            async def complete(self, request: ModelRequest) -> ChatMessage:
                """首轮暂停，后续按确定顺序完成。"""
                self.requests.append(request)
                started.set()
                await release.wait()
                return ChatMessage.assistant("完成")

        model = BlockingModel()
        runtime = assemble_runtime(load_config(configured_project), model, output=lambda _: None)
        tasks: list[asyncio.Task[object]] = []
        try:
            first = asyncio.create_task(runtime.run("第一次认知", run_id="first"))
            tasks.append(first)
            await started.wait()
            second = asyncio.create_task(runtime.launch(CognitionRequest("第二次认知", run_id="second")))
            tasks.append(second)
            await asyncio.sleep(0)
            assert len(model.requests) == 1
            event = EnvironmentEvent(
                "during-inference", "test", "test:world", "message", datetime(2026, 10, 18, tzinfo=UTC), "环境继续变化"
            )
            commit = await runtime.submit_event(event)
            assert await runtime.world.commit(commit.commit_id) == commit
            release.set()
            await asyncio.gather(*tasks)
            assert {result.run_id for result in (first.result(), second.result())} == {"first", "second"}
        finally:
            release.set()
            await asyncio.gather(*tasks, return_exceptions=True)
            await runtime.world.close()

    asyncio.run(scenario())


def test_cancelled_cognition_keeps_started_fact_and_cannot_be_replayed(configured_project: Path) -> None:
    async def scenario() -> None:
        entered = asyncio.Event()
        blocked = asyncio.Event()

        class WaitingModel(FakeModel):
            async def complete(self, request: ModelRequest) -> ChatMessage:
                self.requests.append(request)
                entered.set()
                await blocked.wait()
                raise AssertionError("取消后不得继续执行")

        model = WaitingModel()
        runtime = assemble_runtime(load_config(configured_project), model, output=lambda _: None)
        task = asyncio.create_task(runtime.run("等待结果", run_id="cancelled"))
        try:
            await entered.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert runtime.runtime_status()["runs"] == {
                "running": 0,
                "completed": 0,
                "failed": 0,
                "cancelled": 0,
                "limit_reached": 0,
                "interrupted": 1,
            }
            assert await runtime.world.commit("cancelled:run:started") is not None
            finished = await runtime.world.commit("cancelled:run:finished")
            assert finished is not None and finished.data["status"] == "cancelled"
            with pytest.raises(ValueError, match="已存在"):
                await runtime.run("重复执行", run_id="cancelled")
            assert len(model.requests) == 1
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            await runtime.world.close()

    asyncio.run(scenario())

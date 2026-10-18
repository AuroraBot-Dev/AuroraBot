"""Bot 的输入在进入认知前提交世界，并完整保留触发因果。"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from test_assembly import FakeModel

from aurora import load_config
from src.contracts import ChatMessage, EnvironmentEvent, ModelRequest, TreeLaunchRequest, WorldCommit, WorldFrontier
from src.runtime import assemble_runtime
from src.world import SqlAlchemyWorldJournal

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize("entry", ["runtime", "event", "console", "cadence"])
def test_every_input_path_preserves_its_world_cause(configured_project: Path, entry: str) -> None:
    runtime = assemble_runtime(load_config(configured_project), FakeModel(), output=lambda _: None)

    async def scenario() -> None:
        await runtime.world.initialize()
        try:
            if entry == "runtime":
                tree = await runtime.run("直接输入", tree_id="tree")
            else:
                event = EnvironmentEvent("event", "test", "test:world", "message", datetime.now(UTC), "已提交消息")
                if entry == "event":
                    tree = await runtime.start_tree_from_event(event, tree_id="tree")
                else:
                    commit = await runtime.submit_event(event)
                    if entry == "console":
                        await runtime.terminal.dispatch_terminal(commit.summary, commit=commit)
                        tree = next(iter(runtime._trees.values()))
                    else:
                        tree = await runtime.launch_tree(
                            TreeLaunchRequest(commit.summary, tree_id="tree", caused_by=commit.commit_id)
                        )
            assert tree.caused_by is not None
            cause = await runtime.world.commit(tree.caused_by)
            started = await runtime.world.commit(f"{tree.tree_id}:tree:started")
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
            result = await runtime.start_tree_from_event(event)
            root = result.node(result.root_id)
            disclosed = [message.content for message in root.messages if "world.delta" in message.content]
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
            first = asyncio.create_task(runtime.run("第一次认知", tree_id="first"))
            tasks.append(first)
            await started.wait()
            second = asyncio.create_task(runtime.launch_tree(TreeLaunchRequest("第二次认知", tree_id="second")))
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
            assert {tree.tree_id for tree in runtime._trees.values()} == {"first", "second"}
        finally:
            release.set()
            await asyncio.gather(*tasks, return_exceptions=True)
            await runtime.world.close()

    asyncio.run(scenario())

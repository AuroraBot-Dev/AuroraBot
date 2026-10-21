"""世界存储可由独立模组提供，读写端口跟随实际选中的同一世界。"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

from aurora_bot.contracts import WorldFrontier
from aurora_bot.contracts.pkgs.world import WorldJournal, WorldReader, WorldWriter
from aurora_bot.kernel import compose, compose_managed, module
from aurora_bot.world import SqlAlchemyWorldJournal
from aurora_bot.world.module import MODULE
from tests.kernel.support import Settings as _Settings

if TYPE_CHECKING:
    from pathlib import Path

    from aurora_bot.kernel import AsyncCleanup, ModuleContext


@pytest.mark.parametrize("managed", [False, True])
@pytest.mark.parametrize("all_ports", [False, True])
def test_selected_world_owns_its_configuration_preparation_and_read_write_ports(
    tmp_path: Path, *, managed: bool, all_ports: bool
) -> None:
    path = tmp_path / "selected.sqlite3"
    journal = SqlAlchemyWorldJournal(path)

    async def activate(context: ModuleContext) -> None:
        await context.get(WorldJournal).initialize()

    async def close(context: ModuleContext) -> None:
        await context.get(WorldJournal).close()

    ports = (WorldJournal, WorldReader, WorldWriter) if all_ports else (WorldJournal,)

    @module(name="zzz_selected_world", provides=ports, priority=10, activate=activate, close=close)
    def selected(context: ModuleContext) -> WorldJournal:
        del context
        return journal

    async def scenario() -> None:
        specs = (MODULE, selected)
        handle = await compose_managed(_Settings(), specs) if managed else None
        assembly = handle.assembly if handle is not None else compose(_Settings(), specs)
        try:
            assert assembly.get(WorldJournal) is journal
            assert assembly.get(WorldReader) is journal
            assert assembly.get(WorldWriter) is journal
            assert not path.exists()
            if handle is not None:
                await handle.activate(asyncio.Event())
            else:
                await journal.initialize()
            await assembly.get(WorldWriter).append_commit(
                commit_id="selected-world-input",
                kind="test.input",
                source="test",
                summary="选中的世界可正常读写",
                scopes=frozenset({"test:world/input"}),
                based_on=WorldFrontier(),
                data={},
            )
            assert await assembly.get(WorldReader).commit("selected-world-input") is not None
        finally:
            if handle is not None:
                await handle.close()
            else:
                await journal.close()

    asyncio.run(scenario())


def test_prepared_world_is_borrowed_without_duplicate_initialization_or_cleanup(tmp_path: Path) -> None:
    trace: list[str] = []

    class Journal(SqlAlchemyWorldJournal):
        async def initialize(self) -> None:
            trace.append("initialize")
            await super().initialize()

        async def close(self) -> None:
            trace.append("close")
            await super().close()

    journal = Journal(tmp_path / "prepared.sqlite3")

    async def prepare(context: ModuleContext) -> AsyncCleanup:
        context.provide(WorldJournal, journal)
        await journal.initialize()
        return journal.close

    @module(name="zzz_prepared_world", provides=WorldJournal, priority=10, prepare=prepare)
    def selected(context: ModuleContext) -> WorldJournal:
        return context.get(WorldJournal)

    async def prepare_consumer(context: ModuleContext) -> None:
        assert context.get(WorldWriter) is journal
        trace.append("consumer")

    @module(name="consumer", requires=WorldWriter, prepare=prepare_consumer)
    def consumer(context: ModuleContext) -> None:
        del context

    async def scenario() -> None:
        handle = await compose_managed(_Settings(), (consumer, MODULE, selected))
        try:
            assert trace == ["initialize", "consumer"]
        finally:
            await handle.close()
        assert trace == ["initialize", "consumer", "close"]

    asyncio.run(scenario())

"""``src.world`` 的自描述模块。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.contracts.pkgs.world import WorldJournal, WorldReader, WorldWriter
from src.kernel import ModuleContext, module
from src.world import SqlAlchemyWorldJournal
from src.world.config import StorageConfig, resolve_storage_directory

if TYPE_CHECKING:
    from pathlib import Path

    from src.kernel import AsyncCleanup


def _database_path(context: ModuleContext) -> Path:
    storage = context.settings.resolve(StorageConfig)
    directory = resolve_storage_directory(storage.entries, "world")
    return context.settings.project_root / directory / "world.sqlite3"


async def prepare(context: ModuleContext) -> AsyncCleanup:
    if context.get_optional(WorldJournal) is None:
        context.provide(WorldJournal, SqlAlchemyWorldJournal(_database_path(context)))
    journal = context.get(WorldJournal)
    await journal.initialize()
    if not context.contains(WorldReader):
        context.provide(WorldReader, journal)
    if not context.contains(WorldWriter):
        context.provide(WorldWriter, journal)
    return journal.close


@module(name="world", provides=(WorldReader, WorldWriter, WorldJournal), prepare=prepare)
def build(context: ModuleContext) -> WorldReader:
    existing = context.get_optional(WorldJournal)
    if existing is not None:
        return existing
    return SqlAlchemyWorldJournal(_database_path(context))


MODULE = build

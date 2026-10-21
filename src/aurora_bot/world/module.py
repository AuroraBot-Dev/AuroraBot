"""``aurora_bot.world`` 的自描述模块。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from aurora_bot.contracts.pkgs.world import WorldJournal, WorldReader, WorldWriter
from aurora_bot.kernel import ModuleContext, module
from aurora_bot.world.config import StorageConfig, resolve_storage_directory
from aurora_bot.world.store import SqlAlchemyWorldJournal

if TYPE_CHECKING:
    from aurora_bot.kernel import AsyncCleanup


async def prepare(context: ModuleContext) -> AsyncCleanup | None:
    """仅准备自己提供的存储；读写适配始终使用实际选中的世界。"""
    owns_journal = context.is_provider(WorldJournal)
    journal = context.get_optional(WorldJournal)
    if journal is None:
        if not owns_journal:
            return None
        journal = _create_default(context)
        context.provide(WorldJournal, journal)
    if owns_journal:
        await journal.initialize()
    if not context.contains(WorldReader):
        context.provide(WorldReader, journal)
    if not context.contains(WorldWriter):
        context.provide(WorldWriter, journal)
    return journal.close if owns_journal else None


@module(
    name="world",
    provides=(WorldReader, WorldWriter, WorldJournal),
    requires=WorldJournal,
    prepare=prepare,
)
def build(context: ModuleContext) -> WorldJournal:
    """读写端口与存储端口绑定到同一个已选世界。"""
    journal = context.get_optional(WorldJournal)
    if journal is None:
        journal = _create_default(context)
    return journal


def _create_default(context: ModuleContext) -> WorldJournal:
    """按配置构造默认世界，不初始化或登记公共端口。"""
    storage = context.settings.resolve(StorageConfig)
    directory = resolve_storage_directory(storage.entries, "world")
    path = context.settings.project_root / directory / "world.sqlite3"
    return SqlAlchemyWorldJournal(path)


MODULE = build

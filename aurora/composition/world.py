"""构造并导出 ``src.world`` 的项目实例。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from aurora.composer import InstanceKey
from aurora.configuration.storage import STORAGE_CONFIG
from src.contracts import WorldJournal
from src.world import SqlAlchemyWorldJournal

if TYPE_CHECKING:
    from aurora.composer import CompositionContext
    from aurora.config import AuroraConfig


WORLD_JOURNAL = InstanceKey[WorldJournal]("world.journal")


def register(context: CompositionContext) -> None:
    if context.contains(WORLD_JOURNAL):
        return
    context.provide(WORLD_JOURNAL, build_world(context.config))


def build_world(config: AuroraConfig) -> WorldJournal:
    """为异步启动阶段构造尚未初始化的唯一 WorldJournal。"""
    storage = config.get(STORAGE_CONFIG)
    database_path = config.project_root / storage.data_root / storage.world / "world.sqlite3"
    return SqlAlchemyWorldJournal(database_path)

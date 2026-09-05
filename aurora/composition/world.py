"""构造并导出 ``src.world`` 的项目实例。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from aurora.composer import InstanceKey, PackageSpec
from aurora.configuration.storage import STORAGE_CONFIG, resolve_directory
from src.contracts import WorldJournal
from src.world import SqlAlchemyWorldJournal

if TYPE_CHECKING:
    from aurora.composer import CompositionContext
    from aurora.config import AuroraConfig

WORLD_JOURNAL = InstanceKey[WorldJournal]("world.journal")


def build_world(config: AuroraConfig) -> WorldJournal:
    """为异步启动阶段构造尚未初始化的唯一 WorldJournal。"""
    database_path = config.project_root / resolve_directory(config.get(STORAGE_CONFIG), "world") / "world.sqlite3"
    return SqlAlchemyWorldJournal(database_path)


def construct(context: CompositionContext) -> None:
    """构造并注册 ``src.world`` 的项目实例。"""
    if not context.contains(WORLD_JOURNAL):
        context.provide(WORLD_JOURNAL, build_world(context.config))


PACKAGE_SPEC = PackageSpec(
    key=WORLD_JOURNAL,
    provides=(WORLD_JOURNAL,),
    requires=(),
    register=construct,
)

"""构造并导出 ``src.memory`` 的项目实例。"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, cast

from aurora.composer import InstanceKey, PackageSpec
from aurora.configuration.memory import MEMORY_CONFIG
from src.memory import Memory

if TYPE_CHECKING:
    from aurora.composer import CompositionContext
    from src.contracts import WorldJournal

WORLD_JOURNAL_NAME = "world.journal"

MEMORY = InstanceKey[Memory]("memory.reader")


def construct(context: CompositionContext) -> None:
    configuration = context.config.get(MEMORY_CONFIG)
    journal = cast("WorldJournal", context.require_name(WORLD_JOURNAL_NAME))
    memory = Memory(
        journal,
        window=timedelta(minutes=configuration.window_minutes),
        commits_per_scope=configuration.commits_per_scope,
        scope_include=configuration.scope_include,
        scope_exclude=configuration.scope_exclude,
    )
    context.provide(MEMORY, memory)


PACKAGE_SPEC = PackageSpec(
    key=MEMORY,
    provides=(MEMORY,),
    requires=(WORLD_JOURNAL_NAME,),
    register=construct,
)

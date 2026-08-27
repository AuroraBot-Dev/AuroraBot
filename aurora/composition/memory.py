"""构造并导出 ``src.memory`` 的项目实例。"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

from aurora.composer import InstanceKey
from aurora.composition.world import WORLD_JOURNAL
from aurora.configuration.memory import MEMORY_CONFIG
from src.memory import Memory

if TYPE_CHECKING:
    from aurora.composer import CompositionContext

MEMORY = InstanceKey[Memory]("memory.reader")


def register(context: CompositionContext) -> None:
    configuration = context.config.get(MEMORY_CONFIG)
    context.provide(
        MEMORY,
        Memory(
            context.require(WORLD_JOURNAL),
            window=timedelta(minutes=configuration.window_minutes),
            commits_per_scope=configuration.commits_per_scope,
            scope_include=configuration.scope_include,
            scope_exclude=configuration.scope_exclude,
        ),
    )

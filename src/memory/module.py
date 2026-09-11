"""``src.memory`` 的自描述模块。"""

from __future__ import annotations

from datetime import timedelta

from src.contracts import MemoryReader, WorldJournal
from src.kernel import ModuleContext, module
from src.memory import Memory
from src.memory.config import MemoryConfig


@module(name="memory", provides=MemoryReader, requires=(WorldJournal,))
def build(context: ModuleContext) -> MemoryReader:
    config = context.settings.resolve(MemoryConfig)
    return Memory(
        context.get(WorldJournal),
        window=timedelta(minutes=config.window_minutes),
        commits_per_scope=config.commits_per_scope,
        scope_include=config.scope_include,
        scope_exclude=config.scope_exclude,
    )


MODULE = build

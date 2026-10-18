"""``src.memory`` 的自描述模块。"""

from __future__ import annotations

from datetime import timedelta

from src.contracts import ScopeCatalog
from src.contracts.pkgs.bot import BotStateStore
from src.contracts.pkgs.memory import MemoryReader
from src.contracts.pkgs.world import WorldReader
from src.kernel import ModuleContext, module
from src.memory import Memory
from src.memory.config import MemoryConfig


@module(name="memory", provides=MemoryReader, requires=(WorldReader, BotStateStore))
def build(context: ModuleContext) -> MemoryReader:
    config = context.settings.resolve(MemoryConfig)
    return Memory(
        context.get(WorldReader),
        window=timedelta(minutes=config.window_minutes),
        commits_per_scope=config.commits_per_scope,
        scope_include=config.scope_include,
        scope_exclude=config.scope_exclude,
        catalog=context.settings.resolve(ScopeCatalog),
        state=context.get(BotStateStore),
    )


MODULE = build

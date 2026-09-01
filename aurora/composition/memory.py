"""构造并导出 ``src.memory`` 的项目实例。"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Any

from aurora.composer import InstanceKey, ModuleSpec
from aurora.composition.world import WORLD_JOURNAL
from aurora.configuration.memory import MEMORY_CONFIG
from aurora.views import commit_dict
from src.memory import Memory

if TYPE_CHECKING:
    from aurora.composer import CompositionContext
    from src.contracts import WorldJournal


class MemoryOps:
    """Memory 的窄 ops 端口适配器。"""

    def __init__(self, memory: Memory, world: WorldJournal) -> None:
        self._memory = memory
        self._world = world

    async def memory_snapshot(self) -> dict[str, Any]:
        await self._world.initialize()
        snapshot = await self._memory.recall()
        return {
            "window_start": snapshot.window_start.isoformat(),
            "scopes": [
                {
                    "scope": scope.scope,
                    "head": scope.head,
                    "commits": [commit_dict(commit) for commit in scope.commits],
                }
                for scope in snapshot.scopes
            ],
        }


MEMORY = InstanceKey[Memory]("memory.reader")
MEMORY_OPS = InstanceKey[MemoryOps]("memory.ops")


def _register(context: CompositionContext) -> None:
    configuration = context.config.get(MEMORY_CONFIG)
    journal = context.require(WORLD_JOURNAL)
    memory = Memory(
        journal,
        window=timedelta(minutes=configuration.window_minutes),
        commits_per_scope=configuration.commits_per_scope,
        scope_include=configuration.scope_include,
        scope_exclude=configuration.scope_exclude,
    )
    context.provide(MEMORY, memory)
    context.provide(MEMORY_OPS, MemoryOps(memory, journal))


MODULE_SPEC = ModuleSpec(key=MEMORY, requires=(WORLD_JOURNAL,), register=_register)

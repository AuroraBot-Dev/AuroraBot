"""构造并导出 ``src.memory`` 的项目实例。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from aurora.composer import InstanceKey
from aurora.composition.world import WORLD_JOURNAL
from src.memory import Memory

if TYPE_CHECKING:
    from aurora.composer import CompositionContext

MEMORY = InstanceKey[Memory]("memory.reader")


def register(context: CompositionContext) -> None:
    context.provide(MEMORY, Memory(context.require(WORLD_JOURNAL)))

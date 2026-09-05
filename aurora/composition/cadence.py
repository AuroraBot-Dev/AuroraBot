"""构造并导出 ``src.cadence`` 的项目实例。"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Any

from aurora.composer import InstanceKey, ModuleSpec
from aurora.composition.world import WORLD_JOURNAL
from aurora.configuration.cadence import CADENCE_CONFIG
from src.cadence import DEFAULT_REACTIVE_RULES, Cadence

if TYPE_CHECKING:
    from aurora.composer import CompositionContext
    from src.contracts import WorldJournal


class CadenceOps:
    """Cadence 的窄 ops 端口适配器。"""

    def __init__(self, cadence: Cadence, world: WorldJournal) -> None:
        self._cadence = cadence
        self._world = world

    def cadence_status(self) -> dict[str, Any]:
        return self._cadence.status()

    async def cadence_trigger(self) -> dict[str, Any]:
        await self._world.initialize()
        before = self._cadence.status()
        await self._cadence.evaluate_once()
        return {"before": before, "after": self._cadence.status()}


CADENCE = InstanceKey[Cadence]("cadence.runtime")
CADENCE_OPS = InstanceKey[CadenceOps]("cadence.ops")


def _register(context: CompositionContext) -> None:
    configuration = context.config.get(CADENCE_CONFIG)
    journal = context.require(WORLD_JOURNAL)
    cadence = Cadence(
        journal,
        journal,
        agent=configuration.agent,
        enabled=configuration.enabled,
        evoke_every=configuration.evoke_every,
        tick_every=timedelta(seconds=configuration.tick_seconds),
        poll_interval=configuration.poll_seconds,
        reactive_rules=DEFAULT_REACTIVE_RULES,
    )
    context.provide(CADENCE, cadence)
    context.provide(CADENCE_OPS, CadenceOps(cadence, journal))


MODULE_SPEC = ModuleSpec(key=CADENCE, requires=(WORLD_JOURNAL,), register=_register)

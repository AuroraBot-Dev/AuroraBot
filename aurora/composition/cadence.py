"""构造并导出 ``src.cadence`` 的项目实例。"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

from aurora.composer import InstanceKey
from aurora.composition.world import WORLD_JOURNAL
from aurora.configuration.cadence import CADENCE_CONFIG
from src.cadence import Cadence, ReactiveRule

if TYPE_CHECKING:
    from aurora.composer import CompositionContext

CADENCE = InstanceKey[Cadence]("cadence.runtime")


def register(context: CompositionContext) -> None:
    configuration = context.config.get(CADENCE_CONFIG)
    journal = context.require(WORLD_JOURNAL)
    context.provide(
        CADENCE,
        Cadence(
            journal,
            journal,
            agent=configuration.agent,
            enabled=configuration.enabled,
            evoke_every=configuration.evoke_every,
            tick_every=timedelta(seconds=configuration.tick_seconds),
            poll_interval=configuration.poll_seconds,
            reactive_rules=tuple(
                ReactiveRule(rule.source, rule.event_kind, rule.agent, rule.contains_any)
                for rule in configuration.reactive
            ),
        ),
    )

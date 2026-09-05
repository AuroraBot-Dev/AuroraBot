"""构造并导出 ``src.cadence`` 的项目实例。"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, cast

from aurora.composer import InstanceKey, PackageSpec
from aurora.configuration.cadence import CADENCE_CONFIG
from src.cadence import DEFAULT_REACTIVE_RULES, Cadence

if TYPE_CHECKING:
    import asyncio

    from aurora.composer import CompositionContext
    from src.contracts import WorldJournal

WORLD_JOURNAL_NAME = "world.journal"

CADENCE = InstanceKey[Cadence]("cadence.runtime")


def construct(context: CompositionContext) -> None:
    """构造并注册 ``src.cadence`` 的项目实例。"""
    configuration = context.config.get(CADENCE_CONFIG)
    journal = cast("WorldJournal", context.require_name(WORLD_JOURNAL_NAME))
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


async def activate(context: CompositionContext) -> None:
    """在外部业务事件入口放行前固定世界游标。"""
    cadence = context.require(CADENCE)
    if cadence.enabled:
        await cadence.initialize()


async def run(context: CompositionContext, stop: asyncio.Event) -> None:
    """按统一生命周期运行启用的节律后台循环。"""
    cadence = context.require(CADENCE)
    if cadence.enabled:
        await cadence.run(stop)


PACKAGE_SPEC = PackageSpec(
    key=CADENCE,
    provides=(CADENCE,),
    requires=(WORLD_JOURNAL_NAME,),
    register=construct,
    activate=activate,
    run=run,
)

"""``src.cadence`` 的自描述模块。"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

from src.cadence import DEFAULT_REACTIVE_RULES, Cadence
from src.cadence.config import CadenceConfig
from src.contracts import (
    TREE_LAUNCHER_BINDINGS,
    AgentCatalog,
    WorldJournal,
)
from src.contracts import (
    Cadence as CadencePort,
)
from src.kernel import ModuleContext, module

if TYPE_CHECKING:
    import asyncio


def _validate_agents(agent: str, agents: AgentCatalog) -> None:
    referenced = {agent, *(rule.agent for rule in DEFAULT_REACTIVE_RULES)}
    unknown = referenced - agents.ids
    if unknown:
        raise ValueError(f"cadence 引用了未知 Agent definition：{', '.join(sorted(unknown))}")


async def activate(context: ModuleContext) -> None:
    cadence = context.get(CadencePort)
    if cadence.enabled:
        await cadence.initialize()


async def run(context: ModuleContext, stop: asyncio.Event) -> None:
    cadence = context.get(CadencePort)
    if cadence.enabled:
        await cadence.run(stop)


@module(
    name="cadence",
    provides=CadencePort,
    requires=(WorldJournal, AgentCatalog),
    contributes=(TREE_LAUNCHER_BINDINGS,),
    activate=activate,
    run=run,
)
def build(context: ModuleContext) -> CadencePort:
    config = context.settings.get(CadenceConfig)
    agents = context.get(AgentCatalog)
    _validate_agents(config.agent, agents)
    journal = context.get(WorldJournal)
    cadence = Cadence(
        journal,
        journal,
        agent=config.agent,
        enabled=config.enabled,
        evoke_every=config.evoke_every,
        tick_every=timedelta(seconds=config.tick_seconds),
        poll_interval=config.poll_seconds,
        reactive_rules=DEFAULT_REACTIVE_RULES,
    )
    context.contribute(TREE_LAUNCHER_BINDINGS, cadence.bind_launcher)
    return cadence


MODULE = build

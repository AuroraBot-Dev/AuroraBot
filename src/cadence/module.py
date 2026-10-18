"""``src.cadence`` 的自描述模块。"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

from src.cadence import CADENCE_SCOPE, Cadence, ReactiveRule
from src.cadence.config import CadenceConfig, ReactionsConfig
from src.contracts import TREE_LAUNCHER_BINDINGS
from src.contracts.pkgs.agents import AgentCatalog
from src.contracts.pkgs.cadence import Cadence as CadencePort
from src.contracts.pkgs.world import WorldReader, WorldWriter
from src.kernel import ModuleContext, module

if TYPE_CHECKING:
    import asyncio


def _reactive_rules(config: ReactionsConfig) -> tuple[ReactiveRule, ...]:
    """把配置里的即时路由策略转成运行时规则。"""
    return tuple(ReactiveRule(item.source, item.event_kind, item.agent, item.contains_any) for item in config.reactions)


def _validate_agents(agent: str, rules: tuple[ReactiveRule, ...], agents: AgentCatalog) -> None:
    referenced = {agent, *(rule.agent for rule in rules)}
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
    requires=(WorldReader, WorldWriter, AgentCatalog),
    contributes=(TREE_LAUNCHER_BINDINGS,),
    owns_scopes=CADENCE_SCOPE,
    activate=activate,
    run=run,
)
def build(context: ModuleContext) -> CadencePort:
    config = context.settings.resolve(CadenceConfig)
    rules = _reactive_rules(context.settings.resolve(ReactionsConfig))
    agents = context.get(AgentCatalog)
    _validate_agents(config.agent, rules, agents)
    cadence = Cadence(
        context.get(WorldReader),
        context.get(WorldWriter),
        agent=config.agent,
        enabled=config.enabled,
        evoke_every=config.evoke_every,
        tick_every=timedelta(seconds=config.tick_seconds),
        poll_interval=config.poll_seconds,
        reactive_rules=rules,
    )
    context.contribute(TREE_LAUNCHER_BINDINGS, cadence.bind_launcher)
    return cadence


MODULE = build

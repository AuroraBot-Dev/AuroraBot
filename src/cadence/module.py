"""``src.cadence`` 的自描述模块。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.cadence.cadence import Cadence
from src.cadence.config import CadenceConfig, ReactionsConfig
from src.cadence.reactions import ReactiveRule
from src.contracts import TREE_LAUNCHER_BINDINGS
from src.contracts.pkgs.agents import AgentCatalog
from src.contracts.pkgs.bot import BotStateStore
from src.contracts.pkgs.cadence import Cadence as CadencePort
from src.contracts.pkgs.cadence import RhythmPolicy
from src.contracts.pkgs.world import WorldReader, WorldWriter
from src.contracts.scope import ScopeDeclaration, ScopeKind
from src.kernel import ModuleContext, module

if TYPE_CHECKING:
    import asyncio


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
    requires=(CadencePort, WorldReader, WorldWriter, AgentCatalog, BotStateStore, RhythmPolicy),
    contributes=TREE_LAUNCHER_BINDINGS,
    scopes=ScopeDeclaration(
        "*:world/bot/*/cadence", ScopeKind.RESOURCE, "节律 tick 与唤起决策，记录 Bot 主动发起认知的理由。"
    ),
    activate=activate,
    run=run,
)
def build(context: ModuleContext) -> CadencePort:
    """唤起接线始终绑定实际选中端口，不构造失选的节律。"""
    cadence = context.get_optional(CadencePort)
    if cadence is None:
        config = context.settings.resolve(CadenceConfig)
        reactions = context.settings.resolve(ReactionsConfig)
        rules = tuple(
            ReactiveRule(item.source, item.event_kind, item.agent, item.contains_any) for item in reactions.reactions
        )
        agents = context.get(AgentCatalog)
        _validate_agents(config.agent, rules, agents)
        cadence = Cadence(
            context.get(WorldReader),
            context.get(WorldWriter),
            agent=config.agent,
            enabled=config.enabled,
            policy=context.get(RhythmPolicy),
            state=context.get(BotStateStore),
            poll_interval=config.poll_seconds,
            reactive_rules=rules,
        )
    context.contribute(TREE_LAUNCHER_BINDINGS, cadence.bind_launcher)
    return cadence


def _validate_agents(agent: str, rules: tuple[ReactiveRule, ...], agents: AgentCatalog) -> None:
    referenced = {agent, *(rule.agent for rule in rules)}
    unknown = referenced - agents.ids
    if unknown:
        raise ValueError(f"cadence 引用了未知 Agent definition：{', '.join(sorted(unknown))}")


MODULE = build

"""``aurora_bot.cadence`` 的自描述模块。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from aurora_bot.cadence.cadence import Cadence
from aurora_bot.cadence.config import CadenceConfig, ReactionsConfig
from aurora_bot.cadence.reactions import ReactiveRule
from aurora_bot.contracts import COGNITION_BINDINGS
from aurora_bot.contracts.scope import ScopeDeclaration, ScopeKind
from aurora_bot.kernel import ModuleContext, module

if TYPE_CHECKING:
    import asyncio

    from aurora_bot.contracts.pkgs.agents import AgentCatalog
    from aurora_bot.contracts.pkgs.cadence import Cadence as CadencePort


async def activate(context: ModuleContext) -> None:
    cadence = context.get("cadence")
    if cadence.enabled:
        await cadence.initialize()


async def run(context: ModuleContext, stop: asyncio.Event) -> None:
    cadence = context.get("cadence")
    if cadence.enabled:
        await cadence.run(stop)


@module(
    name="cadence",
    provides="cadence",
    requires=("cadence", "world.reader", "world.writer", "agents", "bot", "rhythm"),
    contributes=COGNITION_BINDINGS,
    scopes=ScopeDeclaration(
        "*:world/bot/*/cadence", ScopeKind.RESOURCE, "节律 tick 与唤起决策，记录 Bot 主动发起认知的理由。"
    ),
    activate=activate,
    run=run,
)
def build(context: ModuleContext) -> CadencePort:
    """唤起接线始终绑定实际选中端口，不构造失选的节律。"""
    cadence = context.get_optional("cadence")
    if cadence is None:
        config = context.settings.resolve(CadenceConfig)
        reactions = context.settings.resolve(ReactionsConfig)
        rules = tuple(
            ReactiveRule(item.source, item.event_kind, item.agent, item.contains_any) for item in reactions.reactions
        )
        agents = context.get("agents")
        _validate_agents(config.agent, rules, agents)
        cadence = Cadence(
            context.get("world.reader"),
            context.get("world.writer"),
            agent=config.agent,
            enabled=config.enabled,
            policy=context.get("rhythm"),
            state=context.get("bot"),
            poll_interval=config.poll_seconds,
            reactive_rules=rules,
        )
    context.contribute(COGNITION_BINDINGS, cadence.bind_launcher)
    return cadence


def _validate_agents(agent: str, rules: tuple[ReactiveRule, ...], agents: AgentCatalog) -> None:
    referenced = {agent, *(rule.agent for rule in rules)}
    unknown = referenced - agents.ids
    if unknown:
        raise ValueError(f"cadence 引用了未知 Agent definition：{', '.join(sorted(unknown))}")


MODULE = build

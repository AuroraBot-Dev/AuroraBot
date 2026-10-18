"""装配持久 Bot 主体并贡献自主状态工具。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.bot.clock import PersistentBotClock
from src.bot.config import BotConfig
from src.bot.operations import bot_operation_specs, bot_operations
from src.bot.store import JournalBotState
from src.contracts import TREE_LAUNCHER_BINDINGS
from src.contracts.operation import OPERATION_CONTRIBUTIONS
from src.contracts.pkgs.bot import BotClock, BotStateStore
from src.contracts.pkgs.world import WorldJournal
from src.contracts.scope import ScopeDeclaration, ScopeKind
from src.kernel import ModuleContext, module

if TYPE_CHECKING:
    import asyncio


async def activate(context: ModuleContext) -> None:
    """外部输入启用前核对持久安排。"""
    await context.get(BotClock).initialize()


async def run(context: ModuleContext, stop: asyncio.Event) -> None:
    """持续兑现主体已经登记的未来活动。"""
    await context.get(BotClock).run(stop)


@module(
    name="bot",
    provides=(BotStateStore, BotClock),
    requires=WorldJournal,
    contributes=(OPERATION_CONTRIBUTIONS, TREE_LAUNCHER_BINDINGS),
    resources=tuple(definition.resource for definition, _parameters in bot_operation_specs()),
    scopes=ScopeDeclaration("*:world/bot/*", ScopeKind.RESOURCE, "Bot 的目标、恢复检查点与唤醒安排。"),
    activate=activate,
    run=run,
)
def build(context: ModuleContext) -> BotStateStore:
    """创建当前配置身份的主体，并发布所属能力。"""
    config = context.settings.resolve(BotConfig)
    world = context.get(WorldJournal)
    state = JournalBotState(world, config.bot_id)
    clock = PersistentBotClock(state, world)
    context.provide(BotClock, clock)
    context.contribute(TREE_LAUNCHER_BINDINGS, clock.bind_launcher)
    for operation in bot_operations(state):
        context.contribute(OPERATION_CONTRIBUTIONS, operation)
    return state


MODULE = build

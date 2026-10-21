"""时间服务作为同级模组，依赖唯一主体并接入实际认知入口。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from aurora_bot.clock.clock import PersistentBotClock
from aurora_bot.contracts import COGNITION_BINDINGS
from aurora_bot.contracts.pkgs.bot import BotStateStore
from aurora_bot.contracts.pkgs.clock import BotClock
from aurora_bot.contracts.pkgs.world import WorldReader
from aurora_bot.kernel import ModuleContext, module

if TYPE_CHECKING:
    import asyncio


async def activate(context: ModuleContext) -> None:
    """外部输入启用前核对选中主体的持久安排。"""
    await context.get(BotClock).initialize()


async def run(context: ModuleContext, stop: asyncio.Event) -> None:
    """持续兑现主体已经登记的未来活动。"""
    await context.get(BotClock).run(stop)


@module(
    name="clock",
    provides=BotClock,
    requires=(BotClock, BotStateStore, WorldReader),
    contributes=COGNITION_BINDINGS,
    activate=activate,
    run=run,
)
def build(context: ModuleContext) -> BotClock:
    """时间服务可独立替换，默认机制仅使用注入的主体状态。"""
    clock = context.get_optional(BotClock)
    if clock is None:
        clock = PersistentBotClock(context.get(BotStateStore), context.get(WorldReader))
    context.contribute(COGNITION_BINDINGS, clock.bind_launcher)
    return clock


MODULE = build

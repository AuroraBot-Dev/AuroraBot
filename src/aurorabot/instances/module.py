"""实例资源只消费主体身份与世界读取能力。"""

from __future__ import annotations

from aurorabot.contracts.pkgs.bot import BotStateStore
from aurorabot.contracts.pkgs.resources import RESOURCE_PROVIDERS
from aurorabot.contracts.pkgs.world import WorldReader
from aurorabot.instances.provider import InstanceProvider
from aurorabot.kernel import ModuleContext, module


@module(
    name="instances",
    requires=(WorldReader, BotStateStore),
    contributes=RESOURCE_PROVIDERS,
)
def build(context: ModuleContext) -> None:
    """独立贡献只读提供者，运行器无需反向依赖资源查询。"""
    context.contribute(
        RESOURCE_PROVIDERS, InstanceProvider(context.get(WorldReader), context.get(BotStateStore).bot_id)
    )


MODULE = build

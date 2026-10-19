"""实例资源只消费主体身份与世界读取能力。"""

from src.contracts.pkgs.bot import BotStateStore
from src.contracts.pkgs.resources import RESOURCE_PROVIDERS
from src.contracts.pkgs.world import WorldReader
from src.instances.provider import InstanceProvider
from src.kernel import ModuleContext, module


@module(name="instances", requires=(WorldReader, BotStateStore), contributes=RESOURCE_PROVIDERS)
def build(context: ModuleContext) -> None:
    """独立贡献只读提供者，运行器无需反向依赖资源查询。"""
    context.contribute(
        RESOURCE_PROVIDERS, InstanceProvider(context.get(WorldReader), context.get(BotStateStore).bot_id)
    )


MODULE = build

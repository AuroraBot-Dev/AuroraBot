"""装配唯一持久主体，并让公开状态操作跟随实际选择。"""

from src.bot.config import BotConfig
from src.bot.operations import bot_operation_specs, bot_operations
from src.bot.store import JournalBotState
from src.contracts.operation import OPERATION_CONTRIBUTIONS
from src.contracts.pkgs.bot import BotStateStore
from src.contracts.pkgs.world import WorldJournal
from src.contracts.scope import ScopeDeclaration, ScopeKind
from src.kernel import ModuleContext, module


@module(
    name="bot",
    provides=BotStateStore,
    requires=(BotStateStore, WorldJournal),
    contributes=OPERATION_CONTRIBUTIONS,
    resources=tuple(definition.resource for definition, _parameters in bot_operation_specs()),
    scopes=ScopeDeclaration("*:world/bot/*", ScopeKind.RESOURCE, "Bot 的目标、恢复检查点与唤醒安排。"),
)
def build(context: ModuleContext) -> BotStateStore:
    """命令与时间服务共享内核选中的主体状态。"""
    state = context.get_optional(BotStateStore)
    if state is None:
        config = context.settings.resolve(BotConfig)
        state = JournalBotState(context.get(WorldJournal), config.bot_id)
    for operation in bot_operations(state):
        context.contribute(OPERATION_CONTRIBUTIONS, operation)
    return state


MODULE = build

"""``src.memory`` 的自描述模块。"""

from __future__ import annotations

from datetime import timedelta

from src.contracts import ScopeCatalog
from src.contracts.operation import OPERATION_CONTRIBUTIONS
from src.contracts.pkgs.bot import BotStateStore
from src.contracts.pkgs.memory import MemoryPolicy, MemoryReader
from src.contracts.pkgs.world import WorldJournal
from src.contracts.scope import ScopeDeclaration, ScopeKind
from src.kernel import ModuleContext, module
from src.memory import Memory
from src.memory.config import MemoryConfig
from src.memory.feedback import MemoryFeedback
from src.memory.index import MemoryIndex
from src.memory.observations import MemoryExposures
from src.memory.queries import MemoryRecallQuery, MemorySourceQuery
from src.memory.replay import MemoryTrainingInput


@module(
    name="memory",
    provides=MemoryReader,
    requires=(MemoryReader, WorldJournal, BotStateStore, MemoryPolicy, ScopeCatalog),
    contributes=(OPERATION_CONTRIBUTIONS,),
    resources=tuple(
        query.DEFINITION.resource
        for query in (MemoryRecallQuery, MemorySourceQuery, MemoryExposures, MemoryFeedback, MemoryTrainingInput)
    ),
    scopes=ScopeDeclaration("*:world/bot/*/memory", ScopeKind.RESOURCE, "记忆使用反馈及修正的持久事实。"),
)
def build(context: ModuleContext) -> MemoryReader:
    """绑定只读经历、主体历史和可替换排序策略。"""
    world = context.get(WorldJournal)
    state = context.get(BotStateStore)
    context.contribute(OPERATION_CONTRIBUTIONS, MemoryExposures(world, state.bot_id))
    context.contribute(OPERATION_CONTRIBUTIONS, MemoryFeedback(world, state))
    index = MemoryIndex(world)
    memory = context.get_optional(MemoryReader)
    if memory is None:
        config = context.settings.resolve(MemoryConfig)
        memory = Memory(
            world,
            policy=context.get(MemoryPolicy),
            window=timedelta(minutes=config.window_minutes),
            commits_per_scope=config.commits_per_scope,
            scope_include=config.scope_include,
            scope_exclude=config.scope_exclude,
            catalog=context.get(ScopeCatalog),
            state=state,
            index=index,
        )
    context.contribute(OPERATION_CONTRIBUTIONS, MemoryRecallQuery(memory))
    context.contribute(OPERATION_CONTRIBUTIONS, MemorySourceQuery(world, index))
    context.contribute(OPERATION_CONTRIBUTIONS, MemoryTrainingInput(world, index, state.bot_id))
    return memory


MODULE = build

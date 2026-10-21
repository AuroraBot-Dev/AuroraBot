"""装配统一操作入口并贡献由定义生成的工具。"""

from __future__ import annotations

from aurora_bot.contracts import TOOL_CONTRIBUTIONS
from aurora_bot.contracts.operation import OPERATION_CONTRIBUTIONS
from aurora_bot.contracts.pkgs.artifacts import ArtifactStore
from aurora_bot.contracts.pkgs.bot import BotStateStore
from aurora_bot.contracts.pkgs.operations import OperationRegistry as OperationRegistryPort
from aurora_bot.contracts.pkgs.resources import ResourceCatalog
from aurora_bot.contracts.pkgs.world import WorldJournal
from aurora_bot.contracts.scope import ScopeDeclaration, ScopeKind
from aurora_bot.kernel import ModuleContext, module
from aurora_bot.operations.registry import OperationRegistry
from aurora_bot.operations.tool import operation_tools


@module(
    name="operations",
    provides=OperationRegistryPort,
    requires=(OperationRegistryPort, BotStateStore, ResourceCatalog, WorldJournal, ArtifactStore),
    contributes=TOOL_CONTRIBUTIONS,
    consumes=OPERATION_CONTRIBUTIONS,
    declares=OPERATION_CONTRIBUTIONS,
    scopes=ScopeDeclaration(
        "*:world/bot/*/operations", ScopeKind.RUN, "领域操作的请求和回执台账；业务事实由所属能力另行提交。"
    ),
)
def build(context: ModuleContext) -> OperationRegistryPort:
    """每个主体绑定一套操作目录与回执世界。"""
    bot_id = context.get(BotStateStore).bot_id
    registry = context.get_optional(OperationRegistryPort)
    if registry is None:
        registry = OperationRegistry(
            bot_id,
            context.contributions(OPERATION_CONTRIBUTIONS),
            context.get(ResourceCatalog),
            context.get(WorldJournal),
            artifacts=context.get(ArtifactStore),
        )
    for tool in operation_tools(registry, bot_id):
        context.contribute(TOOL_CONTRIBUTIONS, tool)
    return registry


MODULE = build

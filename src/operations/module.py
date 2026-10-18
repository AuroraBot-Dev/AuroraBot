"""装配统一操作入口并贡献由定义生成的工具。"""

from src.contracts import TOOL_CONTRIBUTIONS
from src.contracts.operation import OPERATION_CONTRIBUTIONS
from src.contracts.pkgs.artifacts import ArtifactStore
from src.contracts.pkgs.bot import BotStateStore
from src.contracts.pkgs.operations import OperationRegistry as OperationRegistryPort
from src.contracts.pkgs.resources import ResourceCatalog
from src.contracts.pkgs.world import WorldJournal
from src.kernel import ModuleContext, module
from src.operations.registry import OperationRegistry
from src.operations.tool import operation_tools


@module(
    name="operations",
    provides=OperationRegistryPort,
    requires=(BotStateStore, ResourceCatalog, WorldJournal, ArtifactStore),
    consumes=OPERATION_CONTRIBUTIONS,
    contributes=TOOL_CONTRIBUTIONS,
    declares=OPERATION_CONTRIBUTIONS,
    owns_scopes="*:world/bot/*/operations",
)
def build(context: ModuleContext) -> OperationRegistryPort:
    """每个主体绑定一套操作目录与回执世界。"""
    bot_id = context.get(BotStateStore).bot_id
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

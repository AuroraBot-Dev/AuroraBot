"""资源内容存储与操作入口的自描述装配。"""

from __future__ import annotations

from aurorabot.artifacts.config import ArtifactsConfig
from aurorabot.artifacts.discovery import ArtifactFindOperation
from aurorabot.artifacts.operations import ArtifactOperation
from aurorabot.artifacts.provider import ArtifactProvider
from aurorabot.artifacts.store import FileArtifactStore
from aurorabot.contracts.operation import OPERATION_CONTRIBUTIONS
from aurorabot.contracts.pkgs.artifacts import ArtifactStore
from aurorabot.contracts.pkgs.resources import RESOURCE_PROVIDERS
from aurorabot.kernel import ModuleContext, module


async def prepare(context: ModuleContext) -> None:
    """模型在构造前读取权重时，内容端口已经按依赖顺序就绪。"""
    if context.is_provider(ArtifactStore) and not context.contains(ArtifactStore):
        context.provide(ArtifactStore, _create_default(context))


@module(
    name="artifacts",
    provides=ArtifactStore,
    requires=ArtifactStore,
    contributes=(OPERATION_CONTRIBUTIONS, RESOURCE_PROVIDERS),
    resources=(
        ArtifactFindOperation.definition.resource,
        *(ArtifactOperation.definition_for(action).resource for action in ("stat", "read", "put")),
    ),
    prepare=prepare,
)
def build(context: ModuleContext) -> ArtifactStore:
    """启动前提供的同一内容存储继续用于运行期操作。"""
    store = context.get_optional(ArtifactStore)
    if store is None:
        store = _create_default(context)
    context.contribute(RESOURCE_PROVIDERS, ArtifactProvider(store))
    context.contribute(OPERATION_CONTRIBUTIONS, ArtifactFindOperation(store))
    for action in ("stat", "read", "put"):
        context.contribute(OPERATION_CONTRIBUTIONS, ArtifactOperation(store, action))
    return store


def _create_default(context: ModuleContext) -> ArtifactStore:
    """按配置构造默认存储，不选择或登记公共端口。"""
    config = context.settings.resolve(ArtifactsConfig)
    return FileArtifactStore(context.settings.project_root / config.directory)


MODULE = build

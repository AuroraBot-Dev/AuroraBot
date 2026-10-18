"""资源内容存储与操作入口的自描述装配。"""

from src.artifacts.config import ArtifactsConfig
from src.artifacts.discovery import ArtifactFindOperation
from src.artifacts.operations import ArtifactOperation
from src.artifacts.store import FileArtifactStore
from src.contracts.operation import OPERATION_CONTRIBUTIONS
from src.contracts.pkgs.artifacts import ArtifactStore
from src.kernel import ModuleContext, module


def _store(context: ModuleContext) -> ArtifactStore:
    """按配置绑定本机存储，其余模组只依赖公共端口。"""
    existing = context.get_optional(ArtifactStore)
    if existing is not None:
        return existing
    config = context.settings.resolve(ArtifactsConfig)
    return FileArtifactStore(context.settings.project_root / config.directory)


async def prepare(context: ModuleContext) -> None:
    """模型在构造前读取权重时，内容端口已经按依赖顺序就绪。"""
    if context.is_provider(ArtifactStore) and not context.contains(ArtifactStore):
        context.provide(ArtifactStore, _store(context))


@module(
    name="artifacts",
    provides=ArtifactStore,
    requires=ArtifactStore,
    contributes=OPERATION_CONTRIBUTIONS,
    prepare=prepare,
)
def build(context: ModuleContext) -> ArtifactStore:
    """启动前提供的同一内容存储继续用于运行期操作。"""
    store = _store(context)
    context.contribute(OPERATION_CONTRIBUTIONS, ArtifactFindOperation(store))
    for action in ("stat", "read", "put"):
        context.contribute(OPERATION_CONTRIBUTIONS, ArtifactOperation(store, action))
    return store


MODULE = build

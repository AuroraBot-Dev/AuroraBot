"""资源内容存储与操作入口的自描述装配。"""

from src.artifacts.config import ArtifactsConfig
from src.artifacts.operations import ArtifactOperation
from src.artifacts.store import FileArtifactStore
from src.contracts.operation import OPERATION_CONTRIBUTIONS
from src.contracts.pkgs.artifacts import ArtifactStore
from src.kernel import ModuleContext, module


@module(name="artifacts", provides=ArtifactStore, contributes=OPERATION_CONTRIBUTIONS)
def build(context: ModuleContext) -> ArtifactStore:
    """按配置绑定本机存储，其余模组只依赖公共端口。"""
    config = context.settings.resolve(ArtifactsConfig)
    store = FileArtifactStore(context.settings.project_root / config.directory)
    for action in ("stat", "read", "put"):
        context.contribute(OPERATION_CONTRIBUTIONS, ArtifactOperation(store, action))
    return store


MODULE = build

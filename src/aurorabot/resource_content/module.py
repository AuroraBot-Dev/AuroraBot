"""正文发布独立于资源目录与领域能力的构造依赖。"""

from __future__ import annotations

from aurorabot.contracts.artifact import ArtifactInfo
from aurorabot.contracts.module_manifest import MODULE_MANIFEST_MEDIA_TYPE
from aurorabot.contracts.pkgs.artifacts import ArtifactStore
from aurorabot.contracts.resource_content import RESOURCE_CONTENTS, ResourceContent
from aurorabot.kernel import ModuleContext, module


async def ready(context: ModuleContext) -> None:
    """归档可用模组声明与实际贡献正文，保存失败时不启动后台任务。"""
    store = context.get(ArtifactStore)
    contents = (
        *(ResourceContent(spec.resource.ref, spec.content, MODULE_MANIFEST_MEDIA_TYPE) for spec in context.modules),
        *context.contributions(RESOURCE_CONTENTS),
    )
    for resource in contents:
        info = await store.put(resource.ref.key, resource.content, media_type=resource.media_type)
        if info != ArtifactInfo(resource.ref, len(resource.content), resource.media_type):
            raise ValueError(f"资源正文存储返回了不一致的版本或元信息：{resource.ref.key}")


@module(
    name="resource_content",
    requires=ArtifactStore,
    consumes=RESOURCE_CONTENTS,
    declares=RESOURCE_CONTENTS,
    ready=ready,
)
def build(context: ModuleContext) -> None:
    """不创建另一份目录或存储，只履行启动前的正文归档。"""


MODULE = build

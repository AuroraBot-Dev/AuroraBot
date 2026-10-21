"""将内容存储作为动态资源来源，冻结目录无需持有所有已发布版本。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from aurora_bot.contracts.artifact import ArtifactInfo, artifact_revision
from aurora_bot.contracts.artifact_codec import artifact_data
from aurora_bot.contracts.resource import ResourceDescriptor, ResourceKey
from aurora_bot.contracts.resource_query import ResourcePage

if TYPE_CHECKING:
    from aurora_bot.contracts.pkgs.artifacts import ArtifactStore
    from aurora_bot.contracts.resource import ResourceRef
    from aurora_bot.contracts.resource_query import ResourceQuery


class ArtifactProvider:
    """发现仅列清单，检查指定内容时核对完整性。"""

    def __init__(self, store: ArtifactStore) -> None:
        """继续使用装配选中的内容存储，不维护第二份版本列表。"""
        self._store = store

    @property
    def key(self) -> ResourceKey:
        """提供者本身也拥有稳定的命名空间身份。"""
        return ResourceKey("aurora", "artifacts", "provider", "content")

    async def find(self, query: ResourceQuery) -> ResourcePage:
        """内容清单与其他资源遵守同一分页位置。"""
        page = await self._store.find(query)
        return ResourcePage(tuple(_descriptor(info, verified=False) for info in page.items), page.next_cursor)

    async def resolve(self, ref: ResourceRef) -> ResourceDescriptor | None:
        """非内容版本不属于此来源；损坏内容须显式报告而不是伪装成不存在。"""
        try:
            artifact_revision(ref)
        except ValueError:
            return None
        try:
            info = await self._store.stat(ref)
        except LookupError:
            return None
        return _descriptor(info, verified=True)


def _descriptor(info: ArtifactInfo, *, verified: bool) -> ResourceDescriptor:
    """公开逻辑内容描述及检查结果，不披露后端路径。"""
    return ResourceDescriptor(
        info.ref,
        "已发布的资源内容；按固定版本读取正文。",
        metadata={
            "content": artifact_data(info),
            "content_verified": verified,
            "read_operation": "aurora:artifacts/query/read",
        },
    )

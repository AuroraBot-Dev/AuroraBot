"""资源内容存储端口，模型、数据集和回执共享同一版本语义。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from src.contracts.artifact import DEFAULT_ARTIFACT_CHUNK

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

    from src.contracts.artifact import ArtifactChunk, ArtifactInfo, ArtifactPage
    from src.contracts.resource import ResourceKey, ResourceRef
    from src.contracts.resource_query import ResourceQuery


class ArtifactStore(Protocol):
    """资源名称与存储布局分开，所有已发布版本均不可覆盖。"""

    async def put(
        self, key: ResourceKey, content: bytes, *, media_type: str = "application/octet-stream"
    ) -> ArtifactInfo:
        """保存完整字节并返回实际内容版本。"""
        ...

    async def put_stream(
        self, key: ResourceKey, chunks: Iterable[bytes], *, media_type: str = "application/octet-stream"
    ) -> ArtifactInfo:
        """在工作线程中消费同步字节流，不要求整体进入内存。"""
        ...

    async def import_file(
        self, key: ResourceKey, source: Path, *, media_type: str = "application/octet-stream"
    ) -> ArtifactInfo:
        """导入文件快照，源文件发生变化时拒绝发布。"""
        ...

    async def find(self, query: ResourceQuery) -> ArtifactPage:
        """发现已发布版本的元信息，不隐式读取或验证完整正文。"""
        ...

    async def stat(self, ref: ResourceRef) -> ArtifactInfo:
        """核对绑定和内容完整性，返回可公开的描述。"""
        ...

    async def read(self, ref: ResourceRef, *, offset: int = 0, limit: int = DEFAULT_ARTIFACT_CHUNK) -> ArtifactChunk:
        """按固定内容版本读取有界字节块。"""
        ...

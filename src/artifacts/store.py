"""流式、内容寻址、跨重启可校验的本地资源存储。"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import threading
from collections import OrderedDict
from typing import TYPE_CHECKING

from src.artifacts.files import file_chunks, publish, signature, stage
from src.contracts.artifact import (
    DEFAULT_ARTIFACT_CHUNK,
    MAX_ARTIFACT_CHUNK,
    ArtifactChunk,
    ArtifactInfo,
    ArtifactIntegrityError,
    artifact_revision,
)
from src.contracts.resource import ResourceRef

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

    from src.contracts.resource import ResourceKey

_VERIFIED_CACHE_SIZE = 128
_VERIFY_BLOCK = 1024 * 1024
_READ_ATTEMPTS = 3
_MAX_MANIFEST_BYTES = 16 * 1024
type FileSignature = tuple[int, int, int, int, int]


class FileArtifactStore:
    """逻辑名称单独绑定内容，重复字节可共享存储，版本始终固定。"""

    def __init__(self, directory: Path) -> None:
        """文件 I/O 只在异步入口的工作线程中执行。"""
        self._directory = directory.resolve()
        self._verified: OrderedDict[str, FileSignature] = OrderedDict()
        self._cache_lock = threading.Lock()

    async def put(
        self, key: ResourceKey, content: bytes, *, media_type: str = "application/octet-stream"
    ) -> ArtifactInfo:
        """内容摘要确定版本，返回之前完成文件与绑定的发布。"""
        return await self.put_stream(key, (content,), media_type=media_type)

    async def put_stream(
        self, key: ResourceKey, chunks: Iterable[bytes], *, media_type: str = "application/octet-stream"
    ) -> ArtifactInfo:
        """流式写入，不在事件循环中编码或保存大文件。"""
        return await asyncio.to_thread(self._put, key, chunks, media_type)

    async def import_file(
        self, key: ResourceKey, source: Path, *, media_type: str = "application/octet-stream"
    ) -> ArtifactInfo:
        """源文件变化会终止导入，不发布部分内容。"""
        return await self.put_stream(key, file_chunks(source), media_type=media_type)

    async def stat(self, ref: ResourceRef) -> ArtifactInfo:
        """绑定和字节均需有效，缺失内容不伪装成可用资源。"""
        return await asyncio.to_thread(self._stat, ref)

    async def read(self, ref: ResourceRef, *, offset: int = 0, limit: int = DEFAULT_ARTIFACT_CHUNK) -> ArtifactChunk:
        """先验证固定内容版本，再返回所需字节区间。"""
        if type(offset) is not int or type(limit) is not int or offset < 0 or not 0 < limit <= MAX_ARTIFACT_CHUNK:
            raise ValueError(f"资源读取需要非负起点和 1..{MAX_ARTIFACT_CHUNK} 的字节上限")
        return await asyncio.to_thread(self._read, ref, offset, limit)

    def _put(self, key: ResourceKey, chunks: Iterable[bytes], media_type: str) -> ArtifactInfo:
        """先发布内容、再发布绑定；任何异常都不会覆盖已有对象。"""
        staged, digest, size = stage(chunks, self._directory / "temporary")
        try:
            info = ArtifactInfo(ResourceRef(key, digest), size, media_type)
            manifest = json.dumps(
                {
                    "schema_version": 1,
                    "key": str(key),
                    "revision": digest,
                    "size": size,
                    "media_type": media_type,
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            if len(manifest) > _MAX_MANIFEST_BYTES:
                raise ValueError("资源身份和元信息超出清单大小上限")
            publish(staged, self._object_path(digest))
            staged.unlink(missing_ok=True)
            self._read_content(info, 0, 0)
            metadata, _metadata_digest, _size = stage((manifest,), self._directory / "temporary")
            try:
                publish(metadata, self._binding_path(info.ref))
                existing = self._metadata(info.ref)
                if existing != info:
                    raise ValueError("该内容版本已绑定其他资源元信息")
            finally:
                metadata.unlink(missing_ok=True)
            return info
        finally:
            staged.unlink(missing_ok=True)

    def _stat(self, ref: ResourceRef) -> ArtifactInfo:
        """只有核对过的内容才能返回有效描述。"""
        info = self._metadata(ref)
        self._read_content(info, 0, 0)
        return info

    def _read(self, ref: ResourceRef, offset: int, limit: int) -> ArtifactChunk:
        """每个读取在同一打开文件上检查身份和内容。"""
        info = self._metadata(ref)
        if offset > info.size:
            raise ValueError("资源读取起点超出内容大小")
        return ArtifactChunk(info, offset, self._read_content(info, offset, limit))

    def _metadata(self, ref: ResourceRef) -> ArtifactInfo:
        """绑定路径来自逻辑身份摘要，清单不能指定任意后端路径。"""
        path = self._binding_path(ref)
        try:
            with path.open("rb") as stream:
                raw = stream.read(_MAX_MANIFEST_BYTES + 1)
        except FileNotFoundError as error:
            raise LookupError(f"内容资源版本不存在：{ref.key}@{ref.revision}") from error
        try:
            if len(raw) > _MAX_MANIFEST_BYTES:
                raise ValueError("资源绑定超出允许大小")
            data = json.loads(raw)
            if data["schema_version"] != 1 or data["key"] != str(ref.key) or data["revision"] != ref.revision:
                raise ValueError("资源绑定不匹配")
            return ArtifactInfo(ref, data["size"], data["media_type"])
        except (ValueError, TypeError, KeyError) as error:
            raise ArtifactIntegrityError(f"资源绑定已损坏：{ref.key}@{ref.revision}") from error

    def _read_content(self, info: ArtifactInfo, offset: int, limit: int) -> bytes:
        """缓存已验证的文件身份，外部变更会使缓存失效并重新核对摘要。"""
        digest = artifact_revision(info.ref)
        for _ in range(_READ_ATTEMPTS):
            checked = self._checked_content(info, offset, limit)
            if checked is not None:
                content, before = checked
                with self._cache_lock:
                    self._verified[digest] = before
                    self._verified.move_to_end(digest)
                    if len(self._verified) > _VERIFIED_CACHE_SIZE:
                        self._verified.popitem(last=False)
                return content
        raise ArtifactIntegrityError("资源在读取期间持续发生变化")

    def _checked_content(self, info: ArtifactInfo, offset: int, limit: int) -> tuple[bytes, FileSignature] | None:
        """并发发布改变链接计数时重读，稳定的字节必须与摘要匹配。"""
        digest = artifact_revision(info.ref)
        path = self._object_path(digest)
        try:
            with path.open("rb") as stream:
                before = signature(os.fstat(stream.fileno()))
                if before[2] != info.size:
                    raise ArtifactIntegrityError("资源内容大小与绑定不一致")
                with self._cache_lock:
                    known = self._verified.get(digest)
                actual = None
                if known != before:
                    actual = hashlib.sha256()
                    while block := stream.read(_VERIFY_BLOCK):
                        actual.update(block)
                stream.seek(offset)
                content = stream.read(limit)
                if signature(os.fstat(stream.fileno())) != before:
                    return None
                if actual is not None and actual.hexdigest() != digest:
                    raise ArtifactIntegrityError("资源内容摘要与版本不一致")
        except FileNotFoundError as error:
            raise ArtifactIntegrityError("资源绑定存在，但内容已经缺失") from error
        return content, before

    def _object_path(self, digest: str) -> Path:
        """存储布局只使用经过校验的摘要，不插入调用者提供的路径。"""
        return self._directory / "objects" / digest[:2] / digest

    def _binding_path(self, ref: ResourceRef) -> Path:
        """同名资源可拥有多个不可变版本，名称也不能成为文件系统路径。"""
        digest = artifact_revision(ref)
        identity = hashlib.sha256(str(ref.key).encode("utf-8")).hexdigest()
        return self._directory / "bindings" / identity / f"{digest}.json"

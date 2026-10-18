"""操作协议的大对象编解码，共享资源版本与完整性边界。"""

from __future__ import annotations

import asyncio
import json
from itertools import chain
from typing import TYPE_CHECKING, Any

from src.contracts.artifact import MAX_ARTIFACT_CHUNK, ArtifactInfo, ArtifactIntegrityError
from src.contracts.data import freeze_object
from src.utils.json_stream import json_bytes

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from src.contracts.pkgs.artifacts import ArtifactStore
    from src.contracts.resource import ResourceKey


class OperationPayloads:
    """编码与解码在工作线程运行，只有显式恢复时读取完整正文。"""

    def __init__(self, artifacts: ArtifactStore | None, inline_bytes: int) -> None:
        """无存储的独立路由保持内联，正式装配总是提供持久存储。"""
        if type(inline_bytes) is not int or inline_bytes <= 0:
            raise ValueError("操作正文内联上限必须是正整数字节数")
        self._artifacts = artifacts
        self._inline_bytes = inline_bytes

    async def save(
        self, key: ResourceKey, payload: Mapping[str, Any], *, media_type: str
    ) -> Mapping[str, Any] | ArtifactInfo:
        """前缀分类也在线程中执行，超长字符串不会在事件循环中编码。"""
        if self._artifacts is None:
            return payload
        inline, chunks = await asyncio.to_thread(_prepare, payload, self._inline_bytes)
        if inline is not None:
            return inline
        return await self._artifacts.put_stream(key, chunks, media_type=media_type)

    async def load(self, info: ArtifactInfo, *, media_type: str) -> Mapping[str, Any]:
        """引用、分块与描述必须一致，正文缺失不能触发操作重放。"""
        if self._artifacts is None:
            raise ArtifactIntegrityError("操作正文已保存为资源，但当前没有装配内容存储")
        if info.media_type != media_type:
            raise ArtifactIntegrityError("操作正文资源的媒体类型不匹配")
        try:
            payload = bytearray()
            while len(payload) < info.size:
                chunk = await self._artifacts.read(info.ref, offset=len(payload), limit=MAX_ARTIFACT_CHUNK)
                if chunk.info != info or chunk.offset != len(payload) or not chunk.content:
                    raise ArtifactIntegrityError("操作正文分块与已提交描述不一致")
                payload.extend(chunk.content)
            return await asyncio.to_thread(_decode, payload)
        except (ValueError, TypeError, LookupError, OSError) as error:
            raise ArtifactIntegrityError("操作正文资源无法完整恢复") from error


def _prepare(payload: Mapping[str, Any], limit: int) -> tuple[Mapping[str, Any] | None, Iterable[bytes]]:
    """小正文只编码一次，超限后把已消费前缀和剩余流交给内容存储。"""
    chunks = json_bytes(payload)
    prefix = bytearray()
    for chunk in chunks:
        if len(prefix) + len(chunk) > limit:
            return None, chain((bytes(prefix), chunk), chunks)
        prefix.extend(chunk)
    return _decode(prefix), ()


def _decode(content: bytearray) -> Mapping[str, Any]:
    """协议正文必须是不可变 JSON 对象，不接受数组或标量顶层。"""
    data = json.loads(content)
    if not isinstance(data, dict):
        raise ValueError("操作正文必须是 JSON 对象")
    return freeze_object(data)

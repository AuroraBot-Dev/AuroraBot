"""通过公共存储端口显式展开完整内容，读取时继续核对固定版本。"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

from aurora_bot.contracts.artifact import MAX_ARTIFACT_CHUNK, ArtifactIntegrityError

if TYPE_CHECKING:
    from aurora_bot.contracts.artifact import ArtifactInfo
    from aurora_bot.contracts.pkgs.artifacts import ArtifactStore


async def artifact_content(store: ArtifactStore, info: ArtifactInfo) -> bytes:
    """供必须加载完整内容的模型使用，不在模型工具中隐式展开。"""
    if await store.stat(info.ref) != info:
        raise ArtifactIntegrityError("资源元信息与已提交描述不一致")
    chunks: list[bytes] = []
    offset = 0
    digest = hashlib.sha256()
    while offset < info.size:
        chunk = await store.read(info.ref, offset=offset, limit=MAX_ARTIFACT_CHUNK)
        if chunk.info != info or chunk.offset != offset or not chunk.content:
            raise ArtifactIntegrityError("资源分块与已提交描述不一致")
        chunks.append(chunk.content)
        digest.update(chunk.content)
        offset = chunk.next_offset
    if digest.hexdigest() != info.ref.revision:
        raise ArtifactIntegrityError("完整资源内容与指定版本不一致")
    return b"".join(chunks)

"""模型内容的固定版本校验，不依赖具体计算框架。"""

from __future__ import annotations

import hashlib
from io import BytesIO
from typing import TYPE_CHECKING
from zipfile import is_zipfile

from aurora_bot.contracts.artifact import artifact_revision
from aurora_bot.contracts.artifact_io import artifact_content
from aurora_bot.contracts.resource import ResourceKey, ResourceRef

if TYPE_CHECKING:
    from pathlib import Path

    from aurora_bot.contracts.pkgs.artifacts import ArtifactStore

MODEL_MEDIA_TYPE = "application/vnd.aurora.model+pt;version=1"


def model_content_ref(content: bytes, key: ResourceKey, expected: ResourceRef | None = None) -> ResourceRef:
    """摘要取自即将解码的同一份字节，指定版本必须精确相等。"""
    if not isinstance(content, bytes):
        raise TypeError("模型内容必须是不可变 bytes")
    actual = ResourceRef(key, hashlib.sha256(content).hexdigest())
    if expected is not None and actual != expected:
        raise ValueError("模型内容与指定资源版本不一致")
    return actual


def model_weight_reference(key: ResourceKey, weights: str | None, weights_ref: str | None) -> ResourceRef | None:
    """路径与固定资源引用二选一，引用必须属于正在选择的模型。"""
    if weights is not None and weights_ref is not None:
        raise ValueError("weights 与 weights_ref 只能选择一项")
    if weights_ref is None:
        return None
    identity, separator, revision = weights_ref.partition("@")
    if not separator:
        raise ValueError("权重资源必须指定 SHA256 版本")
    ref = ResourceRef(ResourceKey.parse(identity), revision)
    artifact_revision(ref)
    if ref.key != key:
        raise ValueError("权重资源必须属于配置所选的模型")
    return ref


def model_archive(content: bytes) -> BytesIO:
    """只接受当前写入器产生的完整张量归档，不尝试解释任意字节。"""
    stream = BytesIO(content)
    if not is_zipfile(stream):
        raise ValueError("模型内容不是完整的张量归档")
    stream.seek(0)
    return stream


async def read_model_content(
    store: ArtifactStore, key: ResourceKey, *, reference: ResourceRef | None = None, path: Path | None = None
) -> tuple[bytes, ResourceRef]:
    """启动时把文件固定为资源，已有资源按原版本加载，不追随路径后续变化。"""
    if (reference is None) == (path is None):
        raise ValueError("模型加载需要路径或固定资源引用")
    if reference is not None:
        if reference.key != key:
            raise ValueError("权重资源不属于当前模型")
        info = await store.stat(reference)
    else:
        assert path is not None
        info = await store.import_file(key, path, media_type=MODEL_MEDIA_TYPE)
    if info.media_type != MODEL_MEDIA_TYPE:
        raise ValueError("权重资源的媒体类型不匹配")
    return await artifact_content(store, info), info.ref

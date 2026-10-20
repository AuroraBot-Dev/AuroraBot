"""内容资源描述的公开线格式。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from aurorabot.contracts.artifact import ArtifactInfo
from aurorabot.contracts.resource import ResourceKey, ResourceRef


def artifact_data(info: ArtifactInfo) -> dict[str, Any]:
    """返回确定身份与大小，不泄露后端路径。"""
    return {
        "key": str(info.ref.key),
        "revision": info.ref.revision,
        "size": info.size,
        "media_type": info.media_type,
    }


def read_artifact(data: Mapping[str, Any]) -> ArtifactInfo:
    """恢复固定内容版本，复用值对象的完整性约束。"""
    if not isinstance(data, Mapping) or any(
        not isinstance(data.get(field), str) for field in ("key", "revision", "media_type")
    ):
        raise ValueError("内容资源描述必须包含文本身份、版本和媒体类型")
    return ArtifactInfo(ResourceRef(ResourceKey.parse(data["key"]), data["revision"]), data["size"], data["media_type"])

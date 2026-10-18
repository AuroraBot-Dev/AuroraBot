"""内容资源描述的公开线格式。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.contracts.artifact import ArtifactInfo
from src.contracts.resource import ResourceKey, ResourceRef

if TYPE_CHECKING:
    from collections.abc import Mapping


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
    return ArtifactInfo(ResourceRef(ResourceKey.parse(data["key"]), data["revision"]), data["size"], data["media_type"])

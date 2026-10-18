"""有界读取资源清单，逻辑身份始终与存储位置相互核对。"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING

from src.contracts.artifact import ArtifactInfo, ArtifactIntegrityError, artifact_revision
from src.contracts.artifact_codec import read_artifact

if TYPE_CHECKING:
    from pathlib import Path

    from src.contracts.resource import ResourceRef

MAX_MANIFEST_BYTES = 16 * 1024


def binding_path(directory: Path, ref: ResourceRef) -> Path:
    """身份只转换为摘要，不允许资源名称成为本机路径。"""
    digest = artifact_revision(ref)
    identity = hashlib.sha256(str(ref.key).encode("utf-8")).hexdigest()
    return directory / "bindings" / identity / f"{digest}.json"


def read_binding(path: Path, expected: ResourceRef | None = None) -> ArtifactInfo:
    """清单必须符合当前结构，读取固定版本时额外核对调用方身份。"""
    try:
        with path.open("rb") as stream:
            raw = stream.read(MAX_MANIFEST_BYTES + 1)
    except FileNotFoundError as error:
        raise LookupError("内容资源版本不存在") from error
    try:
        if len(raw) > MAX_MANIFEST_BYTES:
            raise ValueError("资源绑定超出允许大小")
        data = json.loads(raw)
        if not isinstance(data, dict) or type(data.get("schema_version")) is not int or data["schema_version"] != 1:
            raise ValueError("资源绑定结构不匹配")
        info = read_artifact(data)
        if expected is not None and info.ref != expected:
            raise ValueError("资源绑定身份不匹配")
        return info
    except (ValueError, TypeError, KeyError) as error:
        raise ArtifactIntegrityError("资源绑定已损坏") from error

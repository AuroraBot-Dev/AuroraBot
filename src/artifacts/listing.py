"""扫描小型清单进行有界分页，不读取资源正文或把目录整体载入内存。"""

from __future__ import annotations

import base64
import binascii
import hashlib
import heapq
import json
import os
from pathlib import Path
from typing import TYPE_CHECKING

from src.artifacts.metadata import binding_path, read_binding
from src.contracts.artifact import ArtifactInfo, ArtifactIntegrityError, ArtifactPage, artifact_revision

if TYPE_CHECKING:
    from collections.abc import Iterator

    from src.contracts.resource_query import ResourceQuery


_MAX_TOKEN_BYTES = 1536
_DIGEST_LENGTH = 64


def find_artifacts(directory: Path, query: ResourceQuery) -> ArtifactPage:
    """按名称摘要与版本排序；每页重新扫描当前清单，内存占用受页大小限制。"""
    after = _position(query)
    matching = (
        info for info in _records(directory) if query.matches(info.ref.key) and (after is None or _order(info) > after)
    )
    found = heapq.nsmallest(query.limit + 1, matching, key=_order)
    items = tuple(found[: query.limit])
    cursor = _cursor(query, items[-1]) if len(found) > query.limit else None
    return ArtifactPage(items, cursor)


def _records(directory: Path) -> Iterator[ArtifactInfo]:
    """只扫描两层绑定目录，拒绝不属于该位置的清单与符号链接。"""
    try:
        parents = os.scandir(directory / "bindings")
    except FileNotFoundError:
        return
    with parents:
        for parent in parents:
            if not parent.is_dir(follow_symlinks=False):
                raise ArtifactIntegrityError("资源绑定目录结构已损坏")
            with os.scandir(parent.path) as entries:
                for entry in entries:
                    if not entry.is_file(follow_symlinks=False):
                        raise ArtifactIntegrityError("资源绑定清单必须是普通文件")
                    path = Path(entry.path)
                    info = read_binding(path)
                    if path != binding_path(directory, info.ref):
                        raise ArtifactIntegrityError("资源绑定位置与逻辑身份不一致")
                    yield info


def _order(info: ArtifactInfo) -> tuple[str, str]:
    """同名资源按固定内容版本排序，不选择所谓最新权重。"""
    return hashlib.sha256(str(info.ref.key).encode()).hexdigest(), artifact_revision(info.ref)


def _cursor(query: ResourceQuery, last: ArtifactInfo) -> str:
    """游标只保存版本化查询条件与最后身份，不携带后端路径。"""
    raw = json.dumps([1, _filters_digest(query), _order(last)], separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode("ascii")


def _position(query: ResourceQuery) -> tuple[str, str] | None:
    """拒绝无效游标和跨筛选复用；分页数量允许调整。"""
    if query.after is None:
        return None
    try:
        raw = base64.b64decode(query.after, altchars=b"-_", validate=True)
        if len(raw) > _MAX_TOKEN_BYTES:
            raise ValueError("资源游标超出上限")
        version, filters, position = json.loads(raw)
        if type(version) is not int or version != 1 or filters != _filters_digest(query):
            raise ValueError("资源游标与筛选条件不一致")
        identity, revision = position
        for value in (identity, revision):
            if (
                not isinstance(value, str)
                or len(value) != _DIGEST_LENGTH
                or any(char not in "0123456789abcdef" for char in value)
            ):
                raise ValueError("资源游标身份无效")
        return identity, revision
    except (ValueError, TypeError, binascii.Error) as error:
        raise ValueError("资源分页游标无效或不属于当前筛选") from error


def _filters_digest(query: ResourceQuery) -> str:
    """固定长度筛选指纹避免长名称扩张分页游标。"""
    return hashlib.sha256(json.dumps(query.filters, separators=(",", ":")).encode()).hexdigest()

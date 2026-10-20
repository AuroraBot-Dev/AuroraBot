"""扫描小型清单进行有界分页，不读取资源正文或把目录整体载入内存。"""

from __future__ import annotations

import heapq
import os
from pathlib import Path
from typing import TYPE_CHECKING

from aurorabot.artifacts.metadata import binding_path, read_binding
from aurorabot.contracts.artifact import ArtifactInfo, ArtifactIntegrityError, ArtifactPage
from aurorabot.contracts.resource_paging import resource_cursor, resource_order, resource_position

if TYPE_CHECKING:
    from collections.abc import Iterator

    from aurorabot.contracts.resource_query import ResourceQuery


def find_artifacts(directory: Path, query: ResourceQuery) -> ArtifactPage:
    """按名称摘要与版本排序；每页重新扫描当前清单，内存占用受页大小限制。"""
    after = resource_position(query)
    matching = (
        info
        for info in _records(directory)
        if query.matches(info.ref.key) and (after is None or resource_order(info.ref) > after)
    )
    found = heapq.nsmallest(query.limit + 1, matching, key=lambda info: resource_order(info.ref))
    items = tuple(found[: query.limit])
    cursor = resource_cursor(query, items[-1].ref) if len(found) > query.limit else None
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

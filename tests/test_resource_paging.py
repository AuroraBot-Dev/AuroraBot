"""提供者间的分页位置可互用，不要求内容版本或有界资源名称。"""

from dataclasses import replace

import pytest

from src.contracts.resource import ResourceKey, ResourceRef
from src.contracts.resource_paging import resource_cursor, resource_order, resource_position
from src.contracts.resource_query import ResourceQuery

_MAX_CURSOR_BYTES = 512


def test_resource_cursor_carries_a_fixed_version_and_filter_boundary() -> None:
    """语义版本和很长的名称不会扩张游标，继续时仍能改变页大小。"""
    reference = ResourceRef(ResourceKey("lab", "memory", "model", "long" * 10000), "release" * 10000)
    query = ResourceQuery(domain="memory", limit=1)
    token = resource_cursor(query, reference)
    assert len(token) < _MAX_CURSOR_BYTES
    assert resource_position(replace(query, limit=100, after=token)) == resource_order(reference)
    with pytest.raises(ValueError, match="当前筛选"):
        resource_position(ResourceQuery(kind="model", after=token))


def test_resource_position_requires_fixed_versions_and_valid_tokens() -> None:
    """未解析别名不能成为排序位置，无效游标不能静默重启。"""
    reference = ResourceRef(ResourceKey("lab", "memory", "model", "tgn"))
    with pytest.raises(ValueError, match="确定版本"):
        resource_order(reference)
    assert resource_position(ResourceQuery()) is None
    for token in ("?", "中文", "e30=", "W10=", "bnVsbA=="):
        with pytest.raises(ValueError, match="游标无效"):
            resource_position(ResourceQuery(after=token))


def test_paging_order_separates_names_and_versions() -> None:
    """同内容的多个名称与同名多个版本都能独立继续。"""
    original = ResourceRef(ResourceKey("lab", "memory", "model", "tgn"), "1")
    assert resource_order(original) != resource_order(replace(original, revision="2"))
    assert resource_order(original) != resource_order(replace(original, key=replace(original.key, path="other")))

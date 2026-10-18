"""验证横向扩展、版本冻结与能力替换边界。"""

from __future__ import annotations

import pytest

from src.contracts.resource import ResourceAlias, ResourceDescriptor, ResourceKey, ResourceRef
from src.resources.catalog import ResourceCatalog


def _definition(namespace: str, revision: str = "1") -> ResourceDescriptor:
    """创建使用同一能力契约的两个独立实现。"""
    return ResourceDescriptor(
        ResourceRef(ResourceKey(namespace, "memory", "model", "ranker"), revision),
        "记忆推荐器",
        ResourceRef(ResourceKey.parse("aurora:memory/contract/recommend"), "1"),
    )


def test_modules_can_add_domains_and_namespaces_without_changing_catalog() -> None:
    """同名资源由命名空间隔离，发现与绑定只依赖公共契约。"""
    local = _definition("local")
    remote = _definition("remote")
    catalog = ResourceCatalog((remote, local))
    assert catalog.find(domain="memory", kind="model") == (local, remote)
    assert catalog.find(namespace="remote") == (remote,)
    assert catalog.find(domain="lighting") == ()
    assert catalog.resolve(local.ref, contract=remote.contract) == local
    incompatible = ResourceRef(ResourceKey.parse("aurora:memory/contract/recommend"), "2")
    with pytest.raises(ValueError, match="能力契约"):
        catalog.resolve(local.ref, contract=incompatible)


def test_alias_freezes_a_specific_version_without_choosing_latest_implicitly() -> None:
    """同时安装多个版本时，省略版本必须通过显式绑定消除歧义。"""
    first = _definition("lab", "1")
    second = _definition("lab", "2")
    alias_key = ResourceKey.parse("aurora:memory/model/default")
    catalog = ResourceCatalog((first, second), (ResourceAlias(alias_key, first.ref),))
    assert catalog.resolve(ResourceRef(alias_key)) == first
    with pytest.raises(LookupError, match="多个版本"):
        catalog.resolve(ResourceRef(first.ref.key))
    assert catalog.resolve(second.ref) == second


def test_unique_version_can_be_bound_and_missing_versions_fail() -> None:
    """单版本发现仍返回可持久化的确定引用。"""
    definition = _definition("lab")
    catalog = ResourceCatalog((definition,))
    assert catalog.resolve(ResourceRef(definition.ref.key)).ref == definition.ref
    with pytest.raises(LookupError, match="版本不存在"):
        catalog.resolve(ResourceRef(definition.ref.key, "missing"))


def test_conflicts_and_dangling_aliases_fail_during_construction() -> None:
    """不依赖安装顺序隐式覆盖资源。"""
    definition = _definition("lab")
    alias = ResourceAlias(ResourceKey.parse("aurora:memory/model/default"), definition.ref)
    with pytest.raises(ValueError, match="重复注册"):
        ResourceCatalog((definition, definition))
    with pytest.raises(ValueError, match="未注册"):
        ResourceCatalog(aliases=(alias,))
    with pytest.raises(ValueError, match="冲突"):
        ResourceCatalog((definition,), (alias, alias))
    with pytest.raises(ValueError, match="冲突"):
        ResourceCatalog((definition,), (ResourceAlias(definition.ref.key, definition.ref),))

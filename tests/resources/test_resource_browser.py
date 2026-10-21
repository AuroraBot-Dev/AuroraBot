"""统一发现跨来源分页，静态定义保持权威且错误来源不能制造隐式漏项。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field, replace

import pytest

from aurora_bot.contracts.resource import ResourceDescriptor, ResourceKey, ResourceRef
from aurora_bot.contracts.resource_paging import resource_cursor, resource_order, resource_position
from aurora_bot.contracts.resource_query import ResourcePage, ResourceQuery
from aurora_bot.resources.catalog import ResourceCatalog


def _descriptor(path: str, description: str = "已发布资源") -> ResourceDescriptor:
    """多个提供者可以发布相同身份，语义差异必须可观察。"""
    return ResourceDescriptor(ResourceRef(ResourceKey("lab", "memory", "dataset", path), "1"), description)


@dataclass(slots=True)
class _Provider:
    """遵守公共分页位置的独立数据来源。"""

    key: ResourceKey
    entries: tuple[ResourceDescriptor, ...]
    calls: list[ResourceQuery] = field(default_factory=list)

    async def find(self, query: ResourceQuery) -> ResourcePage:
        """根据本来源的完整数据确定一页，不共享主目录实现。"""
        self.calls.append(query)
        boundary = resource_position(query)
        matches = sorted(
            (
                item
                for item in self.entries
                if query.matches(item.ref.key) and (boundary is None or resource_order(item.ref) > boundary)
            ),
            key=lambda item: resource_order(item.ref),
        )
        selected = tuple(matches[: query.limit])
        cursor = resource_cursor(query, selected[-1].ref) if len(matches) > query.limit else None
        return ResourcePage(selected, cursor)

    async def resolve(self, ref: ResourceRef) -> ResourceDescriptor | None:
        """精确版本不属于此来源时返回空值。"""
        return next((item for item in self.entries if item.ref == ref), None)


def _provider(name: str, entries: tuple[ResourceDescriptor, ...]) -> _Provider:
    """每个来源拥有独立且可寻址的身份。"""
    return _Provider(ResourceKey("lab", "memory", "provider", name), entries)


def test_merged_pages_are_complete_and_unique_across_static_and_dynamic_sources() -> None:
    """重复版本不占用两次容量，跨来源的后续页不会跳过未见结果。"""
    entries = tuple(_descriptor(f"episode-{index}") for index in range(12))
    first = _provider("first", entries[2:9])
    second = _provider("second", entries[5:])
    catalog = ResourceCatalog(entries[:4], providers=(second, first))

    async def scenario() -> None:
        """每个动态来源每次只被请求一页，全局游标可重建整个结果集。"""
        seen = []
        query = ResourceQuery(domain="memory", limit=2)
        while True:
            page = await catalog.browse(query)
            assert len(page.items) <= query.limit
            seen.extend(page.items)
            if page.next_cursor is None:
                break
            query = replace(query, after=page.next_cursor)
        assert seen == sorted(entries, key=lambda item: resource_order(item.ref))
        assert len(seen) == len({item.ref for item in seen})
        assert first.calls == second.calls
        assert all(call.limit == query.limit for call in first.calls)
        assert catalog.find() == entries[:4]

    asyncio.run(scenario())


def test_static_semantics_win_and_dynamic_conflicts_fail() -> None:
    """已注册定义不会被内容清单遮蔽，多个动态来源也不能改写同一版本含义。"""
    declared = _descriptor("same", "已声明的能力结构")
    first = _provider("first", (replace(declared, description="动态来源一"),))
    second = _provider("second", (replace(declared, description="动态来源二"),))

    async def scenario() -> None:
        """静态声明优先；没有权威声明时冲突必须由提供者解决。"""
        catalog = ResourceCatalog((declared,), providers=(first, second))
        assert (await catalog.browse(ResourceQuery())).items == (declared,)
        assert await catalog.inspect(declared.ref) == declared
        dynamic = ResourceCatalog(providers=(first, second))
        with pytest.raises(ValueError, match="定义不一致"):
            await dynamic.browse(ResourceQuery())
        with pytest.raises(ValueError, match="定义不一致"):
            await dynamic.inspect(declared.ref)

    asyncio.run(scenario())


@dataclass(slots=True)
class _InvalidProvider(_Provider):
    """模拟第三方来源返回不完整或错误的分页。"""

    page: ResourcePage = field(default_factory=lambda: ResourcePage(()))

    async def find(self, query: ResourceQuery) -> ResourcePage:
        """原样返回违反协议的数据，主目录必须拒绝使用。"""
        return self.page


@pytest.mark.parametrize("problem", ["short", "unsorted", "filter", "behind", "cursor", "duplicate", "oversize"])
def test_provider_pages_must_follow_the_shared_boundary(problem: str) -> None:
    """非末页漏填、错误筛选或排序会造成跨来源丢失，不能静默接受。"""
    items = tuple(
        sorted((_descriptor(f"episode-{index}") for index in range(3)), key=lambda item: resource_order(item.ref))
    )
    query = ResourceQuery(namespace="lab", limit=2)
    cases = {
        "short": ResourcePage(items[:1], resource_cursor(query, items[0].ref)),
        "unsorted": ResourcePage((items[1], items[0])),
        "filter": ResourcePage(
            (replace(items[0], ref=replace(items[0].ref, key=replace(items[0].ref.key, namespace="other"))),)
        ),
        "behind": ResourcePage(items[:1]),
        "cursor": ResourcePage(items[:2], resource_cursor(query, items[2].ref)),
        "duplicate": ResourcePage((items[0], items[0])),
        "oversize": ResourcePage(items),
    }
    if problem == "behind":
        query = replace(query, after=resource_cursor(query, items[1].ref))
    provider = _InvalidProvider(ResourceKey("lab", "memory", "provider", "bad"), (), page=cases[problem])
    catalog = ResourceCatalog(providers=(provider,))
    with pytest.raises(ValueError, match="分页协议"):
        asyncio.run(catalog.browse(query))


def test_invalid_cursor_does_not_contact_any_provider_and_duplicate_provider_keys_fail() -> None:
    """查询无效或来源重名时，错误在额外 I/O 前暴露。"""
    provider = _provider("first", ())
    catalog = ResourceCatalog(providers=(provider,))
    with pytest.raises(ValueError, match="游标无效"):
        asyncio.run(catalog.browse(ResourceQuery(after="?")))
    assert provider.calls == []
    with pytest.raises(ValueError, match="提供者身份重复"):
        ResourceCatalog(providers=(provider, provider))


def test_dynamic_inspection_requires_a_version_and_checks_the_requested_contract() -> None:
    """动态内容不猜测最新版本，调用方需要的能力契约也不能被忽略。"""
    descriptor = _descriptor("episode")
    catalog = ResourceCatalog(providers=(_provider("first", (descriptor,)),))

    async def scenario() -> None:
        """未发现的固定版本与契约错误分别保持明确。"""
        assert await catalog.inspect(descriptor.ref) == descriptor
        with pytest.raises(LookupError, match="确定版本"):
            await catalog.inspect(ResourceRef(descriptor.ref.key))
        with pytest.raises(LookupError, match="版本不存在"):
            await catalog.inspect(replace(descriptor.ref, revision="missing"))
        with pytest.raises(ValueError, match="能力契约"):
            await catalog.inspect(
                descriptor.ref, contract=ResourceRef(ResourceKey.parse("lab:memory/contract/reader"), "1")
            )

    asyncio.run(scenario())

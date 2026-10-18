"""合并冻结定义与动态资源来源，分页不会为每个提供者保存额外会话。"""

from __future__ import annotations

import asyncio
import heapq
from types import MappingProxyType
from typing import TYPE_CHECKING

from src.contracts.resource import ResourceDescriptor
from src.contracts.resource_paging import resource_cursor, resource_order, resource_position
from src.contracts.resource_query import ResourcePage

if TYPE_CHECKING:
    from collections.abc import Iterable

    from src.contracts.pkgs.resources import ResourceCatalog, ResourceProvider
    from src.contracts.resource import ResourceRef
    from src.contracts.resource_query import ResourceQuery


class ResourceBrowser:
    """提供者各取一页后合并；静态声明优先，动态同版本冲突明确失败。"""

    def __init__(self, definitions: ResourceCatalog, providers: Iterable[ResourceProvider]) -> None:
        """冻结提供者身份，重名来源在首次查询前拒绝装配。"""
        self._definitions = definitions
        indexed = {}
        for provider in providers:
            if provider.key in indexed:
                raise ValueError(f"资源提供者身份重复：{provider.key}")
            indexed[provider.key] = provider
        self._providers = MappingProxyType(dict(sorted(indexed.items(), key=lambda item: str(item[0]))))

    async def find(self, query: ResourceQuery) -> ResourcePage:
        """一次查询只保留各来源的一页，不把动态版本登记进静态目录。"""
        after = resource_position(query)
        definitions = self._definitions.find(namespace=query.namespace, domain=query.domain, kind=query.kind)
        declared = {item.ref: item for item in definitions}
        eligible = (item for item in definitions if after is None or resource_order(item.ref) > after)
        first = heapq.nsmallest(query.limit + 1, eligible, key=lambda item: resource_order(item.ref))
        static_items = tuple(first[: query.limit])
        static_page = ResourcePage(
            static_items, resource_cursor(query, static_items[-1].ref) if len(first) > query.limit else None
        )
        dynamic = await asyncio.gather(*(provider.find(query) for provider in self._providers.values()))
        for key, page in zip(self._providers, dynamic, strict=True):
            _validate_page(query, page, str(key))
        pages = (static_page, *dynamic)
        merged: dict[ResourceRef, ResourceDescriptor] = {}
        for page in pages:
            for item in page.items:
                if item.ref in declared:
                    merged[item.ref] = declared[item.ref]
                elif item.ref in merged and merged[item.ref] != item:
                    raise ValueError(f"资源提供者对同一版本的定义不一致：{item.ref.key}")
                else:
                    merged[item.ref] = item
        selected = tuple(sorted(merged.values(), key=lambda item: resource_order(item.ref))[: query.limit])
        has_more = len(merged) > query.limit or any(page.next_cursor is not None for page in pages)
        return ResourcePage(selected, resource_cursor(query, selected[-1].ref) if has_more else None)

    async def resolve(self, ref: ResourceRef, *, contract: ResourceRef | None = None) -> ResourceDescriptor:
        """明确版本解析不会隐式选择最新内容，也不掩盖提供者的完整性错误。"""
        try:
            return self._definitions.resolve(ref, contract=contract)
        except LookupError:
            if ref.revision is None:
                raise LookupError(f"动态资源必须指定确定版本：{ref.key}") from None
        candidates = await asyncio.gather(*(provider.resolve(ref) for provider in self._providers.values()))
        found = None
        for candidate in candidates:
            if candidate is None:
                continue
            if not isinstance(candidate, ResourceDescriptor) or candidate.ref != ref:
                raise ValueError("资源提供者返回了其他资源版本")
            if found is not None and candidate != found:
                raise ValueError(f"资源提供者对同一版本的定义不一致：{ref.key}")
            found = candidate
        if found is None:
            raise LookupError(f"资源版本不存在：{ref.key}，版本 {ref.revision}")
        if contract is not None and found.contract != contract:
            raise ValueError(f"资源不满足所需能力契约：{ref.key}")
        return found


def _validate_page(query: ResourceQuery, page: ResourcePage, provider: str) -> None:
    """漏填中间页会跳过未见结果，越界、乱序和错误游标均须明确拒绝。"""
    if not isinstance(page, ResourcePage):
        raise ValueError(f"资源提供者必须返回 ResourcePage：{provider}")
    after = resource_position(query)
    positions = tuple(resource_order(item.ref) for item in page.items)
    invalid = (
        len(page.items) > query.limit
        or positions != tuple(sorted(set(positions)))
        or any(not query.matches(item.ref.key) for item in page.items)
        or any(after is not None and position <= after for position in positions)
    )
    if page.next_cursor is not None:
        invalid = (
            invalid or len(page.items) != query.limit or page.next_cursor != resource_cursor(query, page.items[-1].ref)
        )
    if invalid:
        raise ValueError(f"资源提供者的数量、排序、筛选或游标不符合分页协议：{provider}")

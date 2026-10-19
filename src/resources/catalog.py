"""按命名空间、领域和类别组织的不可变资源目录。"""

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

    from src.contracts.pkgs.resources import ResourceProvider
    from src.contracts.resource import ResourceAlias, ResourceKey, ResourceRef
    from src.contracts.resource_query import ResourceQuery


class ResourceCatalog:
    """目录只保存定义与引用，实际内容仍由所属模组持有。"""

    def __init__(
        self,
        definitions: Iterable[ResourceDescriptor] = (),
        aliases: Iterable[ResourceAlias] = (),
        providers: Iterable[ResourceProvider] = (),
    ) -> None:
        """冻结目录，重名、悬空别名与含混绑定在装配时失败。"""
        entries: dict[ResourceRef, ResourceDescriptor] = {}
        versions: dict[ResourceKey, list[ResourceDescriptor]] = {}
        for descriptor in definitions:
            if descriptor.ref in entries:
                raise ValueError(f"资源版本重复注册：{descriptor.ref.key}，版本 {descriptor.ref.revision}")
            entries[descriptor.ref] = descriptor
            versions.setdefault(descriptor.ref.key, []).append(descriptor)
        bindings: dict[ResourceKey, ResourceRef] = {}
        for alias in aliases:
            if alias.key in bindings or alias.key in versions:
                raise ValueError(f"资源别名与已有身份冲突：{alias.key}")
            if alias.target not in entries:
                raise ValueError(f"资源别名引用了未注册版本：{alias.key}")
            bindings[alias.key] = alias.target
        self._entries = MappingProxyType(entries)
        self._versions = MappingProxyType({key: tuple(values) for key, values in versions.items()})
        self._aliases = MappingProxyType(bindings)
        indexed = {}
        for provider in providers:
            if provider.key in indexed:
                raise ValueError(f"资源提供者身份重复：{provider.key}")
            indexed[provider.key] = provider
        self._providers = MappingProxyType(dict(sorted(indexed.items(), key=lambda item: str(item[0]))))

    def find(
        self, *, namespace: str | None = None, domain: str | None = None, kind: str | None = None
    ) -> tuple[ResourceDescriptor, ...]:
        """按资源维度筛选并稳定排序，发现结果携带确定版本。"""
        matching = (
            entry
            for entry in self._entries.values()
            if (namespace is None or entry.ref.key.namespace == namespace)
            and (domain is None or entry.ref.key.domain == domain)
            and (kind is None or entry.ref.key.kind == kind)
        )
        return tuple(sorted(matching, key=lambda entry: (entry.ref.key, entry.ref.revision or "")))

    def resolve(self, ref: ResourceRef, *, contract: ResourceRef | None = None) -> ResourceDescriptor:
        """只有唯一版本或显式别名可省略版本；绑定后检查能力契约。"""
        if ref.revision is not None:
            target = ref
        elif ref.key in self._aliases:
            target = self._aliases[ref.key]
        else:
            choices = self._versions.get(ref.key, ())
            if len(choices) != 1:
                raise LookupError(f"资源不存在或包含多个版本，请指定版本：{ref.key}")
            target = choices[0].ref
        try:
            descriptor = self._entries[target]
        except KeyError as error:
            raise LookupError(f"资源版本不存在：{target.key}，版本 {target.revision}") from error
        if contract is not None and descriptor.contract != contract:
            raise ValueError(f"资源不满足所需能力契约：{descriptor.ref.key}")
        return descriptor

    async def browse(self, query: ResourceQuery) -> ResourcePage:
        """一次查询只保留各来源的一页，不把动态版本登记进静态目录。"""
        after = resource_position(query)
        definitions = self.find(namespace=query.namespace, domain=query.domain, kind=query.kind)
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

    async def inspect(self, ref: ResourceRef, *, contract: ResourceRef | None = None) -> ResourceDescriptor:
        """明确版本解析不会隐式选择最新内容，也不掩盖提供者的完整性错误。"""
        try:
            return self.resolve(ref, contract=contract)
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

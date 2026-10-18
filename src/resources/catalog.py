"""按命名空间、领域和类别组织的不可变资源目录。"""

from __future__ import annotations

from types import MappingProxyType
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

    from src.contracts.resource import ResourceAlias, ResourceDescriptor, ResourceKey, ResourceRef


class ResourceCatalog:
    """目录只保存定义与引用，实际内容仍由所属模组持有。"""

    def __init__(self, definitions: Iterable[ResourceDescriptor] = (), aliases: Iterable[ResourceAlias] = ()) -> None:
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

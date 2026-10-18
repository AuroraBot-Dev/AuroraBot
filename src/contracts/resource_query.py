"""资源发现的有界筛选条件，分页游标不改变资源版本。"""

from dataclasses import dataclass

from src.contracts.identity import is_namespace
from src.contracts.resource import ResourceDescriptor, ResourceKey

MAX_RESOURCE_PAGE = 100
MAX_RESOURCE_CURSOR_LENGTH = 2048


@dataclass(frozen=True, slots=True)
class ResourceQuery:
    """按独立维度筛选资源，游标只用于继续同一查询。"""

    namespace: str | None = None
    domain: str | None = None
    kind: str | None = None
    limit: int = 20
    after: str | None = None

    def __post_init__(self) -> None:
        """限制响应数量与游标大小，筛选条件使用规范资源语法。"""
        for value in self.filters:
            if value is not None and (not isinstance(value, str) or not is_namespace(value)):
                raise ValueError("资源筛选必须使用合法命名空间、领域或类别")
        if type(self.limit) is not int or not 1 <= self.limit <= MAX_RESOURCE_PAGE:
            raise ValueError(f"资源分页上限必须为 1..{MAX_RESOURCE_PAGE} 的整数")
        if self.after is not None and (
            not isinstance(self.after, str) or not self.after or len(self.after) > MAX_RESOURCE_CURSOR_LENGTH
        ):
            raise ValueError("资源分页游标必须是有界非空文本")

    @property
    def filters(self) -> tuple[str | None, str | None, str | None]:
        """分页必须保持这些筛选维度不变。"""
        return self.namespace, self.domain, self.kind

    def matches(self, key: ResourceKey) -> bool:
        """每个未指定维度均允许匹配。"""
        return all(
            expected is None or expected == actual
            for expected, actual in zip(self.filters, (key.namespace, key.domain, key.kind), strict=True)
        )


@dataclass(frozen=True, slots=True)
class ResourcePage:
    """按公共资源位置严格排序的一页；有后续结果时必须填满请求页。"""

    items: tuple[ResourceDescriptor, ...]
    next_cursor: str | None = None

    def __post_init__(self) -> None:
        """固定返回的定义，游标与查询使用同一大小边界。"""
        object.__setattr__(self, "items", tuple(self.items))
        if any(not isinstance(item, ResourceDescriptor) for item in self.items):
            raise TypeError("资源发现结果必须使用 ResourceDescriptor")
        if self.next_cursor is not None and (
            not isinstance(self.next_cursor, str)
            or not self.next_cursor
            or len(self.next_cursor) > MAX_RESOURCE_CURSOR_LENGTH
        ):
            raise ValueError("资源分页游标必须是有界非空文本")

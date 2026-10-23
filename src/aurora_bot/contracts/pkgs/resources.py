"""资源发现、版本冻结和能力契约检查端口。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from aurora_bot.contracts.kernel import ContributionKey

if TYPE_CHECKING:
    from aurora_bot.contracts.resource import ResourceDescriptor, ResourceKey, ResourceRef
    from aurora_bot.contracts.resource_query import ResourcePage, ResourceQuery


class ResourceProvider(Protocol):
    """动态资源来源，分页必须遵守公共排序、筛选与填满页规则。"""

    @property
    def key(self) -> ResourceKey: ...

    async def find(self, query: ResourceQuery) -> ResourcePage:
        """返回最多 limit 项；非末页必须填满，并用最后版本生成公共游标。"""
        ...

    async def resolve(self, ref: ResourceRef) -> ResourceDescriptor | None:
        """只解析确定版本，不属于本来源的资源返回 None。"""
        ...


RESOURCE_PROVIDERS = ContributionKey[ResourceProvider]("aurora:resources/contribution/providers")


class ResourceCatalog(Protocol):
    """按结构化身份查询资源，解析时冻结确定版本。"""

    def find(
        self, *, namespace: str | None = None, domain: str | None = None, kind: str | None = None
    ) -> tuple[ResourceDescriptor, ...]:
        """按独立维度发现定义，返回稳定顺序。"""
        ...

    def resolve(self, ref: ResourceRef, *, contract: ResourceRef | None = None) -> ResourceDescriptor:
        """解析资源或别名，并验证调用方要求的能力契约。"""
        ...

    async def browse(self, query: ResourceQuery) -> ResourcePage:
        """合并静态定义与动态提供者，按公共资源位置有界分页。"""
        ...

    async def inspect(self, ref: ResourceRef, *, contract: ResourceRef | None = None) -> ResourceDescriptor:
        """优先读取已声明定义，未注册的动态内容需要确定版本。"""
        ...

"""资源发现、版本冻结和能力契约检查端口。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from src.contracts.resource import ResourceDescriptor, ResourceRef


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

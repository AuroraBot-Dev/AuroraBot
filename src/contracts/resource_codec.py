"""统一资源发现与检查返回的公开字段。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.contracts.resource import ResourceDescriptor, ResourceRef
    from src.contracts.resource_query import ResourcePage


def resource_ref_data(ref: ResourceRef) -> dict[str, str | None]:
    """保留完整资源身份与指定版本，不根据名称猜测当前绑定。"""
    return {"key": str(ref.key), "revision": ref.revision}


def resource_data(descriptor: ResourceDescriptor) -> dict[str, Any]:
    """完整保留可调用结构，终端与模型无需维护不同参数说明。"""
    return {
        "resource": str(descriptor.ref.key),
        "revision": descriptor.ref.revision,
        "description": descriptor.description,
        "contract": str(descriptor.contract.key) if descriptor.contract is not None else None,
        "contract_revision": descriptor.contract.revision if descriptor.contract is not None else None,
        "metadata": descriptor.metadata,
    }


def resource_page_data(page: ResourcePage) -> dict[str, Any]:
    """结果说明当前动态列表的续页入口，不宣称历史快照。"""
    return {
        "items": [resource_data(item) for item in page.items],
        "next_cursor": page.next_cursor,
        "listing_mode": "live",
    }

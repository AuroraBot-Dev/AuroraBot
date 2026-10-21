"""统一资源发现与检查返回的公开字段。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from aurora_bot.contracts.resource import ResourceInstance, ResourceKey, ResourceRef

if TYPE_CHECKING:
    from aurora_bot.contracts.resource import ResourceDescriptor
    from aurora_bot.contracts.resource_query import ResourcePage


def resource_ref_data(ref: ResourceRef) -> dict[str, str | None]:
    """保留完整资源身份与指定版本，不根据名称猜测当前绑定。"""
    return {"key": str(ref.key), "revision": ref.revision}


def resource_instance_data(instance: ResourceInstance) -> dict[str, Any]:
    """实例保留原始运行身份和所属 Bot，执行定义使用固定版本。"""
    return {
        "instance_id": instance.instance_id,
        "bot_id": instance.bot_id,
        "definition": resource_ref_data(instance.definition),
    }


def parse_resource_ref(data: object) -> ResourceRef:
    """读取完整引用，拒绝缺失字段、隐式转换及不确定的损坏版本。"""
    if not isinstance(data, Mapping) or set(data) != {"key", "revision"}:
        raise ValueError("资源引用必须包含 key 和 revision")
    key, revision = data["key"], data["revision"]
    if not isinstance(key, str) or (revision is not None and not isinstance(revision, str)):
        raise ValueError("资源引用身份与版本必须使用文本")
    return ResourceRef(ResourceKey.parse(key), revision)


def parse_resource_instance(data: object) -> ResourceInstance:
    """从持久事实读取实例，不用当前配置补写缺失的定义或归属。"""
    if not isinstance(data, Mapping) or set(data) != {"instance_id", "bot_id", "definition"}:
        raise ValueError("资源实例必须包含实例身份、Bot 和定义引用")
    instance_id, bot_id = data["instance_id"], data["bot_id"]
    if not isinstance(instance_id, str) or not isinstance(bot_id, str):
        raise ValueError("资源实例身份与 Bot 必须使用文本")
    return ResourceInstance(instance_id, bot_id, parse_resource_ref(data["definition"]))


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

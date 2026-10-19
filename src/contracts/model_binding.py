"""模型端点与提供方使用独立类别的原生资源身份。"""

from typing import Literal

from src.contracts.resource import ResourceKey


def ai_resource_key(name: str, kind: Literal["endpoint", "provider"]) -> ResourceKey:
    """端点选择与提供方绑定不能借用其他领域或类别的身份。"""
    try:
        key = ResourceKey.parse(name)
        if key.domain == "ai" and key.kind == kind:
            return key
    except ValueError as error:
        raise ValueError(f"模型资源身份必须形如 namespace:ai/{kind}/path：{name}") from error
    raise ValueError(f"模型资源身份必须形如 namespace:ai/{kind}/path：{name}")

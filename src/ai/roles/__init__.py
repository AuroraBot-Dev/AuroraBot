"""预设角色注册表（RFC 0212）：role_id → RoleHandler 类。

配置中的 role 必须是预设之一（预设之外启动报错）；每个预设声明自己的
通道（endpoint）与能力基线，模型绑定由 ``models.toml`` 配置决定。
"""

from __future__ import annotations

from enum import StrEnum

from src.ai.roles.base import RoleHandler
from src.ai.roles.fast import FastRole
from src.ai.roles.multimodal import MultimodalRole
from src.ai.roles.quality import QualityRole


class _Msg(StrEnum):
    """本文件内所有用户或模型可见的硬编码文本。"""

    UNKNOWN_ROLE = "unknown model role '{role}'. Available presets: {available}"


ROLE_PRESETS: dict[str, type[RoleHandler]] = {
    "fast": FastRole,
    "quality": QualityRole,
    "multimodal": MultimodalRole,
}


def resolve(role_id: str) -> type[RoleHandler]:
    """解析预设角色；未预设的 role 抛错（RFC 0212 预设之外不可用）。"""
    handler = ROLE_PRESETS.get(role_id)
    if handler is None:
        raise ValueError(_Msg.UNKNOWN_ROLE.format(role=role_id, available=sorted(ROLE_PRESETS)))
    return handler


__all__ = ["ROLE_PRESETS", "RoleHandler", "resolve"]

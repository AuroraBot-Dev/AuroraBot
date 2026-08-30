"""解析并注册 ``config/platforms.toml`` 的 MCP 客户端偏好。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from aurora.config import ConfigKey
from aurora.utils.toml import boolean, load_toml, require_exact_fields, table

if TYPE_CHECKING:
    from pathlib import Path

    from aurora.config import ConfigCollector


@dataclass(frozen=True, slots=True)
class McpPlatformConfig:
    """MCP 客户端总开关与终端诊断偏好。"""

    enabled: bool
    terminal_logs: bool


@dataclass(frozen=True, slots=True)
class PlatformsConfig:
    """当前项目支持的平台适配偏好。"""

    mcp: McpPlatformConfig


PLATFORMS_CONFIG = ConfigKey[PlatformsConfig]("platforms")


def register(configs: ConfigCollector) -> None:
    configs.register(PLATFORMS_CONFIG, "config/platforms.toml", _parse)


def _parse(path: Path) -> PlatformsConfig:
    document = load_toml(path)
    require_exact_fields(document, frozenset({"platform"}), "platforms.toml")
    platform = table(document, "platform")
    require_exact_fields(platform, frozenset({"mcp"}), "platform")
    mcp = table(platform, "mcp")
    require_exact_fields(mcp, frozenset({"enabled", "terminal_logs"}), "platform.mcp")
    return PlatformsConfig(McpPlatformConfig(boolean(mcp, "enabled"), boolean(mcp, "terminal_logs")))


__all__ = ["PLATFORMS_CONFIG", "McpPlatformConfig", "PlatformsConfig", "register"]

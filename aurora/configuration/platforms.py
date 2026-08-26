"""解析并注册 ``config/platforms.toml`` 的 MCP 客户端偏好。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from aurora.config import ConfigKey
from aurora.utils.toml import TomlTable, boolean, load_toml, table

if TYPE_CHECKING:
    from pathlib import Path

    from aurora.config import ConfigCollector


@dataclass(frozen=True, slots=True)
class McpPlatformConfig:
    """MCP 客户端总开关与终端诊断偏好。"""

    enabled: bool
    terminal_logs: bool

    def __post_init__(self) -> None:
        if not isinstance(self.enabled, bool) or not isinstance(self.terminal_logs, bool):
            raise ValueError("platform.mcp.enabled 与 terminal_logs 必须是布尔值")


@dataclass(frozen=True, slots=True)
class PlatformsConfig:
    """当前项目支持的平台适配偏好。"""

    mcp: McpPlatformConfig


PLATFORMS_CONFIG = ConfigKey[PlatformsConfig]("platforms")


def register(configs: ConfigCollector) -> None:
    configs.register(PLATFORMS_CONFIG, "config/platforms.toml", _parse)


def _parse(path: Path) -> PlatformsConfig:
    document = load_toml(path)
    _require_exact_fields(document, frozenset({"platform"}), "platforms.toml")
    platform = table(document, "platform")
    _require_exact_fields(platform, frozenset({"mcp"}), "platform")
    mcp = table(platform, "mcp")
    _require_exact_fields(mcp, frozenset({"enabled", "terminal_logs"}), "platform.mcp")
    return PlatformsConfig(McpPlatformConfig(boolean(mcp, "enabled"), boolean(mcp, "terminal_logs")))


def _require_exact_fields(document: TomlTable, expected: frozenset[str], label: str) -> None:
    names = set(document)
    if names != expected:
        raise ValueError(f"{label} 字段不匹配：未知 {sorted(names - expected)}，缺少 {sorted(expected - names)}")


__all__ = ["PLATFORMS_CONFIG", "McpPlatformConfig", "PlatformsConfig", "register"]

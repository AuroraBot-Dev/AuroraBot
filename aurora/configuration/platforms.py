"""解析并注册 ``config/platforms.toml`` 的可拓展平台对象。"""

from __future__ import annotations

from dataclasses import dataclass, field

from aurora.config import (
    ConfigSpec,
    TableArrayShape,
    boolean_field,
    optional_table_field,
    optional_text_field,
    text_field,
)

_PLATFORM_IDS = frozenset({"builtin.console", "builtin.panel", "builtin.mcp"})


@dataclass(frozen=True, slots=True)
class PlatformConfig:
    """一个可拓展的平台声明；enabled 与 logging 只解析，暂不驱动实现。"""

    id: str
    enabled: bool
    logging: str | None = None
    config: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.id not in _PLATFORM_IDS:
            raise ValueError(f"未知平台 id：{self.id}")
        normalized = self.logging or "INFO"
        if normalized not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL", "NONE"}:
            raise ValueError("platform.logging 必须是日志级别或 NONE")
        object.__setattr__(self, "logging", normalized)

    def settings(self, key: str, default: object = None) -> object:
        """读取平台私有配置；暂不做类型检查。"""
        return self.config.get(key, default)


PLATFORMS_CONFIG = ConfigSpec[tuple[PlatformConfig, ...]](
    name="platforms",
    path="config/platforms.toml",
    shape=TableArrayShape(
        path=("platform",),
        fields=(
            text_field("id"),
            boolean_field("enabled"),
            optional_text_field("logging"),
            optional_table_field("config"),
        ),
        model=PlatformConfig,
    ),
)

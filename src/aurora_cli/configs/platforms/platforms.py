"""解析并注册 ``config/platforms.toml`` 的可拓展平台对象。"""

from __future__ import annotations

from aurora_bot.mcp.config import PlatformConfig, PlatformsConfig
from aurora_cli.contracts.config import (
    ConfigSpec,
    TableArrayShape,
    boolean_field,
    optional_table_field,
    optional_text_field,
    text_field,
)

CONFIG_SPEC = ConfigSpec[PlatformsConfig](
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
        container=PlatformsConfig,
    ),
)

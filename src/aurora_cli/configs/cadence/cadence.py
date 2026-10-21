"""注册并解析 ``config/cadence.toml`` 的节律策略配置。"""

from __future__ import annotations

from aurora_bot.cadence.config import CadenceConfig
from aurora_cli.contracts.config import (
    ConfigSpec,
    TableShape,
    boolean_field,
    positive_number_field,
    text_field,
)

CONFIG_SPEC = ConfigSpec[CadenceConfig](
    name="cadence",
    path="config/cadence.toml",
    shape=TableShape(
        path=("cadence",),
        fields=(
            boolean_field("enabled"),
            text_field("agent"),
            positive_number_field("poll_seconds"),
        ),
        model=CadenceConfig,
    ),
)

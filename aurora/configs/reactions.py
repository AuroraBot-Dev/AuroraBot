"""注册并解析 ``config/reactions.toml`` 的即时路由规则。"""

from __future__ import annotations

from aurora.contracts.config import ConfigSpec, TableArrayShape, strings_field, text_field
from src.cadence.config import ReactionConfig, ReactionsConfig

REACTIONS_CONFIG = ConfigSpec[ReactionsConfig](
    name="reactions",
    path="config/reactions.toml",
    shape=TableArrayShape(
        path=("reaction",),
        fields=(
            text_field("source"),
            text_field("event_kind"),
            text_field("agent"),
            strings_field("contains_any"),
        ),
        model=ReactionConfig,
        container=ReactionsConfig,
    ),
)

CONFIG_SPEC = REACTIONS_CONFIG

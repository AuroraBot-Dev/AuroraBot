"""注册并解析 ``config/reactions.toml`` 的即时路由规则。"""

from __future__ import annotations

from aurora_bot.cadence.config import ReactionConfig, ReactionsConfig
from aurora_cli.contracts.config import ConfigSpec, TableArrayShape, strings_field, text_field

CONFIG_SPEC = ConfigSpec[ReactionsConfig](
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

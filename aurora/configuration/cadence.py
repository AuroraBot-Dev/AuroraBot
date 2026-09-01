"""注册并解析 ``config/cadence.toml`` 的节律策略配置。"""

from __future__ import annotations

from dataclasses import dataclass

from aurora.config import (
    ConfigSpec,
    TableShape,
    boolean_field,
    positive_integer_field,
    positive_number_field,
    text_field,
)


@dataclass(frozen=True, slots=True)
class CadenceConfig:
    enabled: bool
    agent: str
    evoke_every: int
    tick_seconds: int
    poll_seconds: float


CADENCE_CONFIG = ConfigSpec[CadenceConfig](
    name="cadence",
    path="config/cadence.toml",
    shape=TableShape(
        path=("cadence",),
        fields=(
            boolean_field("enabled"),
            text_field("agent"),
            positive_integer_field("evoke_every"),
            positive_integer_field("tick_seconds"),
            positive_number_field("poll_seconds"),
        ),
        model=CadenceConfig,
    ),
)

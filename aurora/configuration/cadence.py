"""注册并解析 ``config/cadence.toml`` 的节律策略配置。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from aurora.config import ConfigKey
from aurora.utils.toml import boolean, load_toml, positive_integer, table, text

if TYPE_CHECKING:
    from pathlib import Path

    from aurora.config import ConfigCollector


@dataclass(frozen=True, slots=True)
class CadenceConfig:
    enabled: bool
    agent: str
    evoke_every: int
    tick_seconds: int
    poll_seconds: float


CADENCE_CONFIG = ConfigKey[CadenceConfig]("cadence")


def register(configs: ConfigCollector) -> None:
    configs.register(CADENCE_CONFIG, "config/cadence.toml", _parse)


def _parse(path: Path) -> CadenceConfig:
    cadence = table(load_toml(path), "cadence")
    poll_seconds = cadence.get("poll_seconds")
    if not isinstance(poll_seconds, (int, float)) or isinstance(poll_seconds, bool) or poll_seconds <= 0:
        raise ValueError("配置字段 poll_seconds 必须是正数")
    return CadenceConfig(
        boolean(cadence, "enabled"),
        text(cadence, "agent"),
        positive_integer(cadence, "evoke_every"),
        positive_integer(cadence, "tick_seconds"),
        float(poll_seconds),
    )

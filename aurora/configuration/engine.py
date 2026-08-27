"""解析 ``config/engine.toml`` 的 AgentTree 运行上界。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from aurora.config import ConfigKey
from aurora.utils.toml import load_toml, positive_integer, table

if TYPE_CHECKING:
    from pathlib import Path

    from aurora.config import ConfigCollector


@dataclass(frozen=True, slots=True)
class EngineConfig:
    max_depth: int
    max_nodes: int
    max_steps: int


ENGINE_CONFIG = ConfigKey[EngineConfig]("engine")


def register(configs: ConfigCollector) -> None:
    configs.register(ENGINE_CONFIG, "config/engine.toml", _parse)


def _parse(path: Path) -> EngineConfig:
    document = table(table(load_toml(path), "engine"), "tree")
    return EngineConfig(
        positive_integer(document, "max_depth"),
        positive_integer(document, "max_nodes"),
        positive_integer(document, "max_steps"),
    )

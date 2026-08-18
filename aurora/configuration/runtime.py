"""解析 ``config/runtime.toml`` 的 root Agent 入口配置。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from aurora.config import ConfigKey
from aurora.utils.toml import boolean, load_toml, table, text

if TYPE_CHECKING:
    from pathlib import Path

    from aurora.config import ConfigCollector


@dataclass(frozen=True, slots=True)
class RuntimeConfig:
    node_id: str
    agent: str
    console_enabled: bool


RUNTIME_CONFIG = ConfigKey[RuntimeConfig]("runtime")


def register(configs: ConfigCollector) -> None:
    configs.register(RUNTIME_CONFIG, "config/runtime.toml", _parse)


def _parse(path: Path) -> RuntimeConfig:
    runtime = table(load_toml(path), "runtime")
    tree = table(runtime, "tree")
    console = table(runtime, "console")
    return RuntimeConfig(
        text(tree, "node_id"),
        text(tree, "agent"),
        boolean(console, "enabled"),
    )

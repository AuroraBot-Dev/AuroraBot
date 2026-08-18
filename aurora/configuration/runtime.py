"""解析 ``config/runtime.toml`` 的 root Agent 入口配置。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from aurora.config import ConfigKey
from aurora.utils.toml import load_toml, strings, text

if TYPE_CHECKING:
    from pathlib import Path

    from aurora.config import ConfigCollector


@dataclass(frozen=True, slots=True)
class RuntimeConfig:
    node_id: str
    profile: str
    model: str
    tools: frozenset[str]


RUNTIME_CONFIG = ConfigKey[RuntimeConfig]("runtime")


def register(configs: ConfigCollector) -> None:
    configs.register(RUNTIME_CONFIG, "config/runtime.toml", _parse)


def _parse(path: Path) -> RuntimeConfig:
    document = load_toml(path)
    return RuntimeConfig(
        text(document, "node_id"),
        text(document, "profile"),
        text(document, "model"),
        frozenset(strings(document, "tools")),
    )

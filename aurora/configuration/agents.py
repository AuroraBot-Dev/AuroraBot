"""解析并注册 ``config/agents.toml`` 的预定义 Agent 原型。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from aurora.config import ConfigKey
from aurora.utils.toml import TomlTable, load_toml, strings, text

if TYPE_CHECKING:
    from pathlib import Path

    from aurora.config import ConfigCollector


@dataclass(frozen=True, slots=True)
class AgentConfig:
    definition_id: str
    description: str
    prompt: str
    model: str
    tools: frozenset[str]
    children: frozenset[str]


@dataclass(frozen=True, slots=True)
class AgentsConfig:
    definitions: tuple[AgentConfig, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "definitions", tuple(self.definitions))
        if not self.definitions:
            raise ValueError("agents.toml 至少需要一个 Agent definition")


AGENTS_CONFIG = ConfigKey[AgentsConfig]("agents")


def register(configs: ConfigCollector) -> None:
    configs.register(AGENTS_CONFIG, "config/agents.toml", _parse)


def _parse(path: Path) -> AgentsConfig:
    raw_definitions = load_toml(path).get("agent")
    if not isinstance(raw_definitions, tuple) or any(not isinstance(item, Mapping) for item in raw_definitions):
        raise ValueError("agents.toml 的 agent 必须是非空表数组")
    return AgentsConfig(
        tuple(
            AgentConfig(
                text(item, "id"),
                text(item, "description"),
                text(item, "prompt"),
                text(item, "model"),
                frozenset(strings(item, "tools")),
                frozenset(strings(item, "children")),
            )
            for raw in raw_definitions
            for item in (cast("TomlTable", raw),)
        )
    )

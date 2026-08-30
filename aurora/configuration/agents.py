"""解析并注册 ``config/agents.toml`` 的预定义 Agent 原型。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from aurora.config import ConfigKey
from aurora.utils.toml import (
    load_toml,
    non_empty_text,
    strings,
    table_array,
    text,
    text_array,
)

if TYPE_CHECKING:
    from pathlib import Path

    from aurora.config import ConfigCollector


@dataclass(frozen=True, slots=True)
class AgentConfig:
    definition_id: str
    description: str
    prompt: str
    model: str
    tools: tuple[str, ...]
    children: frozenset[str]

    def __post_init__(self) -> None:
        non_empty_text(self.definition_id, "definition_id")
        non_empty_text(self.description, "description")
        non_empty_text(self.prompt, "prompt")
        non_empty_text(self.model, "model")
        text_array(self.tools, "tools")
        text_array(tuple(self.children), "children")


@dataclass(frozen=True, slots=True)
class AgentsConfig:
    definitions: tuple[AgentConfig, ...]

    def __post_init__(self) -> None:
        if not self.definitions:
            raise ValueError("agents.toml 至少需要一个 Agent definition")


AGENTS_CONFIG = ConfigKey[AgentsConfig]("agents")


def register(configs: ConfigCollector) -> None:
    configs.register(AGENTS_CONFIG, "config/agents.toml", _parse)


def _parse(path: Path) -> AgentsConfig:
    raw_definitions = table_array(load_toml(path), "agent")
    return AgentsConfig(
        tuple(
            AgentConfig(
                text(item, "id"),
                text(item, "description"),
                text(item, "prompt"),
                text(item, "model"),
                strings(item, "tools"),
                frozenset(strings(item, "children")),
            )
            for item in raw_definitions
        )
    )

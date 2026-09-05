"""解析并注册 ``config/agents.toml`` 的预定义 Agent 原型。"""

from __future__ import annotations

from dataclasses import dataclass

from aurora.config import (
    ConfigSpec,
    TableArrayShape,
    strings_field,
    text_field,
)


@dataclass(frozen=True, slots=True)
class AgentConfig:
    id: str
    description: str
    prompt: str
    model: str
    tools: tuple[str, ...]
    children: frozenset[str]


AGENTS_CONFIG = ConfigSpec[tuple[AgentConfig, ...]](
    name="agents",
    path="config/agents.toml",
    shape=TableArrayShape(
        path=("agent",),
        fields=(
            text_field("id"),
            text_field("description"),
            text_field("prompt"),
            text_field("model"),
            strings_field("tools"),
            strings_field("children", transform=frozenset),
        ),
        model=AgentConfig,
    ),
)

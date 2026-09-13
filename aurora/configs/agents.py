"""解析并注册 ``config/agents.toml`` 的预定义 Agent 原型。"""

from __future__ import annotations

from aurora.contracts.config import ConfigSpec, TableArrayShape, strings_field, text_field
from src.agents.config import AgentConfig, AgentsConfig

AGENTS_CONFIG = ConfigSpec[AgentsConfig](
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
        container=AgentsConfig,
    ),
)

CONFIG_SPEC = AGENTS_CONFIG

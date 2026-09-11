"""``src.agents`` 的配置形状。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AgentConfig:
    """一个预定义 Agent 原型。"""

    id: str
    description: str
    prompt: str
    model: str
    tools: tuple[str, ...]
    children: frozenset[str]


@dataclass(frozen=True, slots=True)
class AgentsConfig:
    """``agents.toml`` 的全部 Agent 原型。"""

    agents: tuple[AgentConfig, ...]

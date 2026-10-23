from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from aurora_bot.contracts.agent_resource import agent_content
from aurora_bot.contracts.identity import (
    AGENT_PATH_PREFIX,
    PROMPT_PATH_PREFIX,
    TOOL_PATH_PREFIX,
    Identifier,
    matches_species,
)
from aurora_bot.contracts.model_binding import ai_resource_key
from aurora_bot.contracts.resource import ResourceKey, ResourceRef


@dataclass(frozen=True, slots=True)
class AgentDefinition:
    definition_id: str
    description: str
    prompt_id: str
    model: str
    tools: frozenset[str]
    content: bytes = field(init=False, repr=False)
    ref: ResourceRef = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "tools", frozenset(self.tools))
        if not self.description.strip():
            raise ValueError("Agent 需要描述")
        if not matches_species(self.definition_id, AGENT_PATH_PREFIX):
            raise ValueError(f"Agent definition ID 无效：{self.definition_id}")
        if not matches_species(self.prompt_id, PROMPT_PATH_PREFIX):
            raise ValueError(f"Agent prompt ID 无效：{self.prompt_id}")
        ai_resource_key(self.model, "endpoint")
        if any(not matches_species(name, TOOL_PATH_PREFIX) for name in self.tools):
            raise ValueError(f"Agent 引用了非工具 ID：{self.definition_id}")
        content = agent_content(self)
        object.__setattr__(self, "content", content)
        object.__setattr__(
            self, "ref", ResourceRef(ResourceKey.parse(self.definition_id), hashlib.sha256(content).hexdigest())
        )


def _focus_goals(values: tuple[str, ...]) -> tuple[str, ...]:
    goals = tuple(values)
    if len(set(goals)) != len(goals):
        raise ValueError("认知焦点目标不能重复")
    if any(not Identifier.parse(goal_id).path.startswith("goal/") for goal_id in goals):
        raise ValueError("认知焦点必须引用目标身份")
    return goals

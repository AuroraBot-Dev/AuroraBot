"""与具体运行对象无关的组合配置值。"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping


@dataclass(frozen=True, slots=True)
class RootAgentConfiguration:
    node_id: str
    profile: str
    model: str
    tools: frozenset[str]


@dataclass(frozen=True, slots=True)
class RunnerConfiguration:
    max_depth: int = 4
    max_nodes: int = 32
    max_steps: int = 256
    max_prompt_characters: int = 32_000


@dataclass(frozen=True, slots=True)
class PromptConfiguration:
    system: tuple[str, ...]
    profiles: Mapping[str, str]

    def __post_init__(self) -> None:
        system = tuple(part.strip() for part in self.system if part.strip())
        profiles = {key: value.strip() for key, value in self.profiles.items() if key and value.strip()}
        if not system:
            raise ValueError("prompt configuration requires at least one system fragment")
        if not profiles:
            raise ValueError("prompt configuration requires at least one profile")
        object.__setattr__(self, "system", system)
        object.__setattr__(self, "profiles", MappingProxyType(profiles))


@dataclass(frozen=True, slots=True)
class AuroraConfiguration:
    root: RootAgentConfiguration
    runner: RunnerConfiguration
    prompt: PromptConfiguration

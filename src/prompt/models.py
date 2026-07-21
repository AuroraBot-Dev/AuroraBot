"""Immutable prompt catalog and layered assembly DTOs."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING

from src.contracts.model import ModelMessage

_INVALID_SECTION = "prompt sections require a key and non-empty content"
_INVALID_CATALOG = "prompt catalog requires string soul and non-empty world"
_INVALID_AGENT_PROMPTS = "prompt catalog requires non-empty Agent prompts"

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path


@dataclass(frozen=True, slots=True)
class PromptSource:
    path: Path
    sha256: str


@dataclass(frozen=True, slots=True)
class PromptCatalog:
    soul: str
    world: str
    agents: Mapping[str, str]
    sources: tuple[PromptSource, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.soul, str) or not isinstance(self.world, str) or not self.world.strip():
            raise ValueError(_INVALID_CATALOG)
        agents = dict(self.agents)
        invalid = any(
            not isinstance(key, str) or not key or not isinstance(value, str) or not value.strip()
            for key, value in agents.items()
        )
        if not agents or invalid:
            raise ValueError(_INVALID_AGENT_PROMPTS)
        object.__setattr__(self, "agents", MappingProxyType(agents))
        object.__setattr__(self, "sources", tuple(self.sources))

    @classmethod
    def create(
        cls,
        *,
        soul: str,
        world: str,
        agents: Mapping[str, str],
        sources: tuple[PromptSource, ...] = (),
    ) -> "PromptCatalog":
        return cls(soul, world, agents, sources)


@dataclass(frozen=True, slots=True)
class PromptSection:
    key: str
    content: str

    def __post_init__(self) -> None:
        if not self.key or not self.content.strip():
            raise ValueError(_INVALID_SECTION)


@dataclass(frozen=True, slots=True)
class PromptDocument:
    system_sections: tuple[PromptSection, ...]
    user_sections: tuple[PromptSection, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "system_sections", tuple(self.system_sections))
        object.__setattr__(self, "user_sections", tuple(self.user_sections))

    @property
    def system_prompt(self) -> str:
        return "\n\n".join(section.content.strip() for section in self.system_sections)

    @property
    def user_prompt(self) -> str:
        return "\n\n".join(section.content.strip() for section in self.user_sections)

    def messages(self) -> tuple[ModelMessage, ModelMessage]:
        return ModelMessage("system", self.system_prompt), ModelMessage("user", self.user_prompt)

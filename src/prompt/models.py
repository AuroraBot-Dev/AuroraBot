"""PromptAssembler 使用的最小不可变提示词目录。"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping


@dataclass(frozen=True, slots=True)
class PromptCatalog:
    """全局 system 片段与 profile 局部提示词。"""

    system: tuple[str, ...]
    profiles: Mapping[str, str]

    def __post_init__(self) -> None:
        system = tuple(part.strip() for part in self.system if part.strip())
        profiles = {key: value.strip() for key, value in self.profiles.items() if key and value.strip()}
        if not system:
            raise ValueError("PromptCatalog requires at least one system fragment")
        if not profiles:
            raise ValueError("PromptCatalog requires at least one profile prompt")
        object.__setattr__(self, "system", system)
        object.__setattr__(self, "profiles", MappingProxyType(profiles))

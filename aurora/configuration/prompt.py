"""解析 ``config/prompt.toml`` 的提示词目录配置。"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING

from aurora.config import ConfigKey
from aurora.utils.toml import load_toml, positive_integer, string_mapping, strings

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from aurora.config import ConfigCollector


@dataclass(frozen=True, slots=True)
class PromptConfig:
    system: tuple[str, ...]
    profiles: Mapping[str, str]
    max_characters: int

    def __post_init__(self) -> None:
        if not self.system:
            raise ValueError("提示词配置至少需要一个 system 片段")
        if not self.profiles:
            raise ValueError("提示词配置至少需要一个 profile")
        object.__setattr__(self, "profiles", MappingProxyType(dict(self.profiles)))


PROMPT_CONFIG = ConfigKey[PromptConfig]("prompt")


def register(configs: ConfigCollector) -> None:
    configs.register(PROMPT_CONFIG, "config/prompt.toml", _parse)


def _parse(path: Path) -> PromptConfig:
    document = load_toml(path)
    return PromptConfig(
        strings(document, "system"),
        string_mapping(document, "profiles"),
        positive_integer(document, "max_characters"),
    )

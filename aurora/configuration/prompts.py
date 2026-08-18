"""解析 ``config/prompts.toml`` 及其引用的提示词正文。"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING

from aurora.config import ConfigKey
from aurora.utils.toml import load_toml, positive_integer, string_mapping, table, text

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


PROMPTS_CONFIG = ConfigKey[PromptConfig]("prompts")


def register(configs: ConfigCollector) -> None:
    configs.register(PROMPTS_CONFIG, "config/prompts.toml", _parse)


def _parse(path: Path) -> PromptConfig:
    document = load_toml(path)
    system_paths = table(document, "system")
    agent_paths = string_mapping(document, "agent")
    return PromptConfig(
        tuple(_read_fragment(path.parent, text(system_paths, name)) for name in ("soul", "world")),
        {profile: _read_fragment(path.parent, relative_path) for profile, relative_path in agent_paths.items()},
        positive_integer(document, "max_characters"),
    )


def _read_fragment(config_directory: Path, relative_path: str) -> str:
    value = (config_directory / relative_path).read_text(encoding="utf-8").strip()
    if not value:
        raise ValueError(f"提示词文件不能为空：{relative_path}")
    return value

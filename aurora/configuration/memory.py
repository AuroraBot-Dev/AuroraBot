"""注册并解析 ``config/memory.toml`` 的记忆召回配置。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from aurora.config import ConfigKey
from aurora.utils.toml import check_positive_integer, load_toml, positive_integer, strings, table, text_array

if TYPE_CHECKING:
    from pathlib import Path

    from aurora.config import ConfigCollector


@dataclass(frozen=True, slots=True)
class MemoryConfig:
    window_minutes: int
    commits_per_scope: int
    scope_include: tuple[str, ...]
    scope_exclude: tuple[str, ...]

    def __post_init__(self) -> None:
        check_positive_integer(self.window_minutes, "window_minutes")
        check_positive_integer(self.commits_per_scope, "commits_per_scope")
        text_array(self.scope_include, "scope_include")
        text_array(self.scope_exclude, "scope_exclude")


MEMORY_CONFIG = ConfigKey[MemoryConfig]("memory")


def register(configs: ConfigCollector) -> None:
    configs.register(MEMORY_CONFIG, "config/memory.toml", _parse)


def _parse(path: Path) -> MemoryConfig:
    memory = table(load_toml(path), "memory")
    return MemoryConfig(
        positive_integer(memory, "window_minutes"),
        positive_integer(memory, "commits_per_scope"),
        strings(memory, "scope_include"),
        strings(memory, "scope_exclude"),
    )

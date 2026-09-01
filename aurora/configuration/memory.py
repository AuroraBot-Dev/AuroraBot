"""注册并解析 ``config/memory.toml`` 的记忆召回配置。"""

from __future__ import annotations

from dataclasses import dataclass

from aurora.config import ConfigSpec, TableShape, positive_integer_field, strings_field


@dataclass(frozen=True, slots=True)
class MemoryConfig:
    window_minutes: int
    commits_per_scope: int
    scope_include: tuple[str, ...]
    scope_exclude: tuple[str, ...]


MEMORY_CONFIG = ConfigSpec[MemoryConfig](
    name="memory",
    path="config/memory.toml",
    shape=TableShape(
        path=("memory",),
        fields=(
            positive_integer_field("window_minutes"),
            positive_integer_field("commits_per_scope"),
            strings_field("scope_include"),
            strings_field("scope_exclude"),
        ),
        model=MemoryConfig,
    ),
)

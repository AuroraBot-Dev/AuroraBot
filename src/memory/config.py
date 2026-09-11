"""``src.memory`` 的配置形状。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MemoryConfig:
    """近期世界记忆召回配置。"""

    window_minutes: int
    commits_per_scope: int
    scope_include: tuple[str, ...]
    scope_exclude: tuple[str, ...]

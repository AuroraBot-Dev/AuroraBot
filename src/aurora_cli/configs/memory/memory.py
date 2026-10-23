"""注册并解析 ``config/memory.toml`` 的记忆召回配置。"""

from __future__ import annotations

from aurora_bot.memory.config import MemoryConfig
from aurora_cli.contracts.config import ConfigSpec, TableShape, positive_integer_field, strings_field

CONFIG_SPEC = ConfigSpec[MemoryConfig](
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

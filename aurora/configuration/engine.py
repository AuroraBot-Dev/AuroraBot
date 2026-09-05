"""解析并注册 ``config/engine.toml`` 的 AgentTree 运行上界。"""

from __future__ import annotations

from dataclasses import dataclass

from aurora.config import ConfigSpec, TableShape, positive_integer_field


@dataclass(frozen=True, slots=True)
class EngineConfig:
    max_depth: int
    max_nodes: int
    max_steps: int


ENGINE_CONFIG = ConfigSpec[EngineConfig](
    name="engine",
    path="config/engine.toml",
    shape=TableShape(
        path=("engine", "tree"),
        fields=(
            positive_integer_field("max_depth"),
            positive_integer_field("max_nodes"),
            positive_integer_field("max_steps"),
        ),
        model=EngineConfig,
    ),
)

"""解析并注册 ``config/engine.toml`` 的 AgentTree 运行上界。"""

from __future__ import annotations

from aurora_bot.engine.config import EngineConfig
from aurora_cli.contracts.config import ConfigSpec, TableShape, positive_integer_field

CONFIG_SPEC = ConfigSpec[EngineConfig](
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

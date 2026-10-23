from __future__ import annotations

from aurora_bot.engine.config import EngineConfig
from aurora_cli.contracts.config import ConfigSpec, TableShape, positive_integer_field

CONFIG_SPEC = ConfigSpec[EngineConfig](
    name="engine",
    path="config/engine.toml",
    shape=TableShape(
        path=("engine", "run"),
        fields=(
            positive_integer_field("max_model_calls"),
            positive_integer_field("max_tool_calls"),
            positive_integer_field("max_context_chars"),
        ),
        model=EngineConfig,
    ),
)

"""解析 ``config/runtime.toml`` 的进程级运行时配置。"""

from __future__ import annotations

from aurora.contracts.config import ConfigSpec, TableShape, text_field
from src.runtime.config import RuntimeConfig

CONFIG_SPEC = ConfigSpec[RuntimeConfig](
    name="runtime",
    path="config/runtime.toml",
    shape=TableShape(
        path=("runtime",),
        fields=(
            text_field("profile"),
            text_field("node_id"),
            text_field("agent"),
            text_field("log_level"),
        ),
        model=RuntimeConfig,
    ),
)

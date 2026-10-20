"""解析并注册 ``config/endpoints.toml`` 的模型端点配置。"""

from __future__ import annotations

from aurora.contracts.config import ConfigSpec, TableArrayShape, text_field
from aurorabot.ai.config import EndpointConfig, EndpointsConfig

CONFIG_SPEC = ConfigSpec[EndpointsConfig](
    name="endpoints",
    path="config/endpoints.toml",
    shape=TableArrayShape(
        path=("endpoint",),
        fields=(
            text_field("name"),
            text_field("provider"),
            text_field("model"),
        ),
        model=EndpointConfig,
        container=EndpointsConfig,
    ),
)

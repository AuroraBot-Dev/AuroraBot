"""解析并注册 ``config/endpoints.toml`` 的模型端点配置。"""

from __future__ import annotations

from aurora.config import ConfigSpec, TableArrayShape, text_field
from src.ai.config import EndpointConfig, EndpointsConfig

ENDPOINTS_CONFIG = ConfigSpec[EndpointsConfig](
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

CONFIG_SPEC = ENDPOINTS_CONFIG

"""解析并注册 ``config/endpoints.toml`` 的模型端点配置。"""

from __future__ import annotations

from dataclasses import dataclass

from aurora.config import ConfigSpec, TableArrayShape, text_field


@dataclass(frozen=True, slots=True)
class EndpointConfig:
    name: str
    provider: str
    model: str


ENDPOINTS_CONFIG = ConfigSpec[tuple[EndpointConfig, ...]](
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
    ),
)

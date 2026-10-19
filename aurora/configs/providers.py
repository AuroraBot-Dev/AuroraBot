"""解析并注册 ``config/providers.toml`` 的模型提供商配置。"""

from __future__ import annotations

from aurora.contracts.config import ConfigSpec, TableArrayShape, optional_text_field, text_field
from src.ai.config import ProviderConfig, ProvidersConfig

PROVIDERS_CONFIG = ConfigSpec[ProvidersConfig](
    name="providers",
    path="config/providers.toml",
    shape=TableArrayShape(
        path=("provider",),
        fields=(
            text_field("name"),
            text_field("adapter"),
            text_field("secret_env"),
            optional_text_field("base_url"),
            optional_text_field("sdk_provider"),
        ),
        model=ProviderConfig,
        container=ProvidersConfig,
    ),
)

CONFIG_SPEC = PROVIDERS_CONFIG

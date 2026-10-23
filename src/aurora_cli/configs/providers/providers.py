"""解析并注册 ``config/providers.toml`` 的模型提供商配置。"""

from __future__ import annotations

from aurora_bot.ai.config import ProviderConfig, ProvidersConfig
from aurora_cli.contracts.config import ConfigSpec, TableArrayShape, optional_text_field, text_field

CONFIG_SPEC = ConfigSpec[ProvidersConfig](
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

"""解析并注册 ``config/providers.toml`` 的模型提供商配置。"""

from __future__ import annotations

from dataclasses import dataclass

from aurora.config import (
    ConfigSpec,
    TableArrayShape,
    optional_text_field,
    text_field,
)


@dataclass(frozen=True, slots=True)
class ProviderConfig:
    name: str
    adapter: str
    secret_env: str
    base_url: str | None = None


PROVIDERS_CONFIG = ConfigSpec[tuple[ProviderConfig, ...]](
    name="providers",
    path="config/providers.toml",
    shape=TableArrayShape(
        path=("provider",),
        fields=(
            text_field("name"),
            text_field("adapter"),
            text_field("secret_env"),
            optional_text_field("base_url"),
        ),
        model=ProviderConfig,
    ),
)

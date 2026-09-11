"""``src.ai`` 的配置形状。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ProviderConfig:
    """一个模型提供商端点。"""

    name: str
    adapter: str
    secret_env: str
    base_url: str | None = None


@dataclass(frozen=True, slots=True)
class EndpointConfig:
    """一个显式模型端点。"""

    name: str
    provider: str
    model: str


@dataclass(frozen=True, slots=True)
class ProvidersConfig:
    """``providers.toml`` 的全部提供商。"""

    providers: tuple[ProviderConfig, ...]


@dataclass(frozen=True, slots=True)
class EndpointsConfig:
    """``endpoints.toml`` 的全部模型端点。"""

    endpoints: tuple[EndpointConfig, ...]

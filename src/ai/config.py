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
class ProvidersConfig:
    """``providers.toml`` 的全部提供商。"""

    providers: tuple[ProviderConfig, ...]

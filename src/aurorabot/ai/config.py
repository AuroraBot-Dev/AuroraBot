"""``aurorabot.ai`` 的配置形状。"""

from __future__ import annotations

from dataclasses import dataclass

from aurorabot.contracts.model_binding import ai_resource_key


@dataclass(frozen=True, slots=True)
class ProviderConfig:
    """一个模型提供商端点。"""

    name: str
    adapter: str
    secret_env: str
    base_url: str | None = None
    sdk_provider: str | None = None

    def __post_init__(self) -> None:
        """提供方名称就是其资源身份，不通过默认命名空间隐式补全。"""
        ai_resource_key(self.name, "provider")


@dataclass(frozen=True, slots=True)
class ProvidersConfig:
    """``providers.toml`` 的全部提供商。"""

    providers: tuple[ProviderConfig, ...]


@dataclass(frozen=True, slots=True)
class EndpointConfig:
    """一个显式模型端点。"""

    name: str
    provider: str
    model: str

    def __post_init__(self) -> None:
        """端点与提供方引用完整身份，远端模型名称保留原始协议值。"""
        ai_resource_key(self.name, "endpoint")
        ai_resource_key(self.provider, "provider")


@dataclass(frozen=True, slots=True)
class EndpointsConfig:
    """``endpoints.toml`` 的全部模型端点。"""

    endpoints: tuple[EndpointConfig, ...]

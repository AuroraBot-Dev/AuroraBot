"""注册 ``config/models.toml``。"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING

from aurora.config import ConfigKey
from aurora.utils.toml import (
    check_positive_integer,
    check_positive_number,
    load_toml,
    named_tables,
    optional_text,
    positive_integer,
    positive_number,
    table,
    text,
)

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from aurora.config import ConfigCollector


@dataclass(frozen=True, slots=True)
class ProviderConfig:
    adapter: str
    secret_env: str
    base_url: str | None = None


@dataclass(frozen=True, slots=True)
class ModelEndpointConfig:
    provider: str
    model: str


@dataclass(frozen=True, slots=True)
class ModelRuntimeConfig:
    attempt_timeout_seconds: float
    max_attempts: int
    total_timeout_seconds: float
    max_output_tokens: int

    def __post_init__(self) -> None:
        check_positive_number(self.attempt_timeout_seconds, "attempt_timeout_seconds")
        check_positive_number(self.total_timeout_seconds, "total_timeout_seconds")
        if self.total_timeout_seconds < self.attempt_timeout_seconds:
            raise ValueError("模型总超时不能小于单次 attempt 超时")
        check_positive_integer(self.max_output_tokens, "max_output_tokens")
        object.__setattr__(self, "attempt_timeout_seconds", float(self.attempt_timeout_seconds))
        object.__setattr__(self, "total_timeout_seconds", float(self.total_timeout_seconds))


@dataclass(frozen=True, slots=True)
class ModelsConfig:
    providers: Mapping[str, ProviderConfig]
    endpoints: Mapping[str, ModelEndpointConfig]
    runtime: ModelRuntimeConfig

    def __post_init__(self) -> None:
        object.__setattr__(self, "providers", MappingProxyType(dict(self.providers)))
        object.__setattr__(self, "endpoints", MappingProxyType(dict(self.endpoints)))


MODELS_CONFIG = ConfigKey[ModelsConfig]("models")


def register(configs: ConfigCollector) -> None:
    configs.register(MODELS_CONFIG, "config/models.toml", _parse)


def _parse(path: Path) -> ModelsConfig:
    models = table(load_toml(path), "models")
    providers = {
        provider_id: ProviderConfig(
            text(provider, "adapter"),
            text(provider, "secret_env"),
            optional_text(provider, "base_url"),
        )
        for provider_id, provider in named_tables(models, "providers").items()
    }
    endpoints = {
        endpoint_id: ModelEndpointConfig(text(endpoint, "provider"), text(endpoint, "model"))
        for endpoint_id, endpoint in named_tables(models, "endpoints").items()
    }
    if not providers or not endpoints:
        raise ValueError("models.toml 至少需要一个 provider 和一个模型端点")
    unknown = {endpoint.provider for endpoint in endpoints.values()} - providers.keys()
    if unknown:
        raise ValueError(f"模型端点引用了未知 provider：{', '.join(sorted(unknown))}")
    runtime = table(models, "runtime")
    return ModelsConfig(
        providers,
        endpoints,
        ModelRuntimeConfig(
            positive_number(runtime, "attempt_timeout_seconds"),
            positive_integer(runtime, "max_attempts"),
            positive_number(runtime, "total_timeout_seconds"),
            positive_integer(runtime, "max_output_tokens"),
        ),
    )

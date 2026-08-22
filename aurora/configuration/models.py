"""注册 ``config/models.toml``。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, cast

from aurora.config import ConfigKey
from aurora.utils.toml import TomlTable, load_toml, table, text

if TYPE_CHECKING:
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
class ModelsConfig:
    providers: Mapping[str, ProviderConfig]
    endpoints: Mapping[str, ModelEndpointConfig]

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
            _optional_text(provider, "base_url"),
        )
        for provider_id, provider in _named_tables(models, "providers").items()
    }
    endpoints = {
        endpoint_id: ModelEndpointConfig(text(endpoint, "provider"), text(endpoint, "model"))
        for endpoint_id, endpoint in _named_tables(models, "endpoints").items()
    }
    if not providers or not endpoints:
        raise ValueError("models.toml 至少需要一个 provider 和一个模型端点")
    unknown = {endpoint.provider for endpoint in endpoints.values()} - providers.keys()
    if unknown:
        raise ValueError(f"模型端点引用了未知 provider：{', '.join(sorted(unknown))}")
    return ModelsConfig(providers, endpoints)


def _named_tables(document: TomlTable, key: str) -> dict[str, TomlTable]:
    values = table(document, key)
    result: dict[str, TomlTable] = {}
    for name, value in values.items():
        if not isinstance(name, str) or not name.strip() or not isinstance(value, Mapping):
            raise ValueError(f"配置字段 {key} 必须只包含命名表")
        result[name.strip()] = cast("TomlTable", value)
    return result


def _optional_text(document: TomlTable, key: str) -> str | None:
    value = document.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"配置字段 {key} 必须是非空文本")
    return value.strip()

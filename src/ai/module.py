"""``src.ai`` 的自描述模块。"""

from __future__ import annotations

from src.ai import LiteLLMModelGateway, ModelEndpoint, ProviderEndpoint
from src.ai.config import ProvidersConfig
from src.contracts import EndpointsConfig, Model
from src.kernel import ModuleContext, module


@module(name="ai", provides=Model)
def build(context: ModuleContext) -> Model:
    providers = context.settings.resolve(ProvidersConfig)
    endpoints = context.settings.resolve(EndpointsConfig)
    return LiteLLMModelGateway(
        {item.name: ProviderEndpoint(item.adapter, item.base_url, item.secret_env) for item in providers.providers},
        {item.name: ModelEndpoint(item.provider, item.model) for item in endpoints.endpoints},
    )


MODULE = build

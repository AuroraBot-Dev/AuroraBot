"""构造并导出 ``src.ai`` 的项目 Model 实例。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from aurora.composer import InstanceKey, ModuleSpec
from aurora.configuration.endpoints import ENDPOINTS_CONFIG
from aurora.configuration.providers import PROVIDERS_CONFIG
from src.ai import LiteLLMModelGateway, ModelEndpoint, ProviderEndpoint
from src.contracts import Model

if TYPE_CHECKING:
    from aurora.composer import CompositionContext
    from aurora.configuration.endpoints import EndpointConfig
    from aurora.configuration.providers import ProviderConfig


class AiOps:
    """providers/endpoints 配置的窄 ops 端口适配器。"""

    def __init__(self, providers: tuple[ProviderConfig, ...], endpoints: tuple[EndpointConfig, ...]) -> None:
        self._providers = providers
        self._endpoints = endpoints

    def model_catalog(self) -> dict[str, Any]:
        return {
            "providers": [
                {
                    "provider_id": provider.name,
                    "adapter": provider.adapter,
                    "secret_env": provider.secret_env,
                    "base_url": provider.base_url,
                }
                for provider in self._providers
            ],
            "endpoints": [
                {"endpoint_id": endpoint.name, "provider": endpoint.provider, "model": endpoint.model}
                for endpoint in self._endpoints
            ],
        }

    def model_detail(self, endpoint_id: str) -> dict[str, Any] | None:
        endpoint = next((item for item in self._endpoints if item.name == endpoint_id), None)
        if endpoint is None:
            return None
        provider = next((item for item in self._providers if item.name == endpoint.provider), None)
        return {
            "endpoint_id": endpoint_id,
            "provider": endpoint.provider,
            "model": endpoint.model,
            "adapter": provider.adapter if provider else None,
            "secret_env": provider.secret_env if provider else None,
            "base_url": provider.base_url if provider else None,
        }


MODEL = InstanceKey[Model]("ai.model")
AI_OPS = InstanceKey[AiOps]("ai.ops")


def _register(context: CompositionContext) -> None:
    providers = context.config.get(PROVIDERS_CONFIG)
    endpoints = context.config.get(ENDPOINTS_CONFIG)
    if not context.contains(MODEL):
        context.provide(
            MODEL,
            LiteLLMModelGateway(
                {
                    provider.name: ProviderEndpoint(provider.adapter, provider.base_url, provider.secret_env)
                    for provider in providers
                },
                {endpoint.name: ModelEndpoint(endpoint.provider, endpoint.model) for endpoint in endpoints},
            ),
        )
    context.provide(AI_OPS, AiOps(providers, endpoints))


MODULE_SPEC = ModuleSpec(key=MODEL, requires=(), register=_register)

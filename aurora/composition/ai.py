"""构造并导出 ``src.ai`` 的项目实例。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from aurora.composer import InstanceKey, PackageSpec
from aurora.configuration.endpoints import ENDPOINTS_CONFIG
from aurora.configuration.providers import PROVIDERS_CONFIG
from src.ai import LiteLLMModelGateway, ModelEndpoint, ProviderEndpoint
from src.contracts import Model

if TYPE_CHECKING:
    from aurora.composer import CompositionContext

MODEL = InstanceKey[Model]("ai.model")


def construct(context: CompositionContext) -> None:
    """构造并注册 ``src.ai`` 的项目实例。"""
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


PACKAGE_SPEC = PackageSpec(
    key=MODEL,
    provides=(MODEL,),
    requires=(),
    register=construct,
)

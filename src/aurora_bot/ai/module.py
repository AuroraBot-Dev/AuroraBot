"""``aurora_bot.ai`` 的自描述模块。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from aurora_bot.ai.config import EndpointsConfig, ProvidersConfig
from aurora_bot.ai.gateway import LiteLLMModelGateway, ModelEndpoint, ProviderEndpoint
from aurora_bot.contracts.model_binding import MODEL_BINDING_MEDIA_TYPE, PROVIDER_MEDIA_TYPE
from aurora_bot.contracts.resource_content import RESOURCE_CONTENTS, ResourceContent
from aurora_bot.kernel import ModuleContext, module
from aurora_bot.kernel.hooks import service_namespace

if TYPE_CHECKING:
    from aurora_bot.contracts.pkgs.ai import Model

CALLS = service_namespace(
    "ai", "ai", methods=("resolve_endpoint",), asynchronous=("complete",), attributes=("providers", "endpoints")
)


@module(
    name="ai",
    provides="ai",
    requires="ai",
    contributes=RESOURCE_CONTENTS,
    points=CALLS.spec.points,
    handlers=CALLS.spec.handlers,
)
def build(context: ModuleContext) -> Model:
    """归档实际选中模型实现的端点，配置文件不替代真实提供方的执行声明。"""
    model = context.get_optional("ai")
    if model is None:
        providers = context.settings.resolve(ProvidersConfig)
        endpoints = context.settings.resolve(EndpointsConfig)
        model = LiteLLMModelGateway(
            {
                item.name: ProviderEndpoint(item.adapter, item.base_url, item.secret_env, item.sdk_provider)
                for item in providers.providers
            },
            {item.name: ModelEndpoint(item.provider, item.model) for item in endpoints.endpoints},
        )
    for provider in model.providers:
        context.contribute(RESOURCE_CONTENTS, ResourceContent(provider.ref, provider.content, PROVIDER_MEDIA_TYPE))
    for endpoint in model.endpoints:
        context.contribute(RESOURCE_CONTENTS, ResourceContent(endpoint.ref, endpoint.content, MODEL_BINDING_MEDIA_TYPE))
    return model


MODULE = build

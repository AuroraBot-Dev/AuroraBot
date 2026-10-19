"""``src.ai`` 的自描述模块。"""

from __future__ import annotations

from src.ai import LiteLLMModelGateway, ModelEndpoint, ProviderEndpoint
from src.ai.config import EndpointsConfig, ProvidersConfig
from src.contracts.model_binding import MODEL_BINDING_MEDIA_TYPE, PROVIDER_MEDIA_TYPE
from src.contracts.pkgs.ai import Model
from src.contracts.resource_content import RESOURCE_CONTENTS, ResourceContent
from src.kernel import ModuleContext, module


@module(name="ai", provides=Model, requires=Model, contributes=RESOURCE_CONTENTS)
def build(context: ModuleContext) -> Model:
    """归档实际选中模型实现的端点，配置文件不替代真实提供方的执行声明。"""
    model = context.get_optional(Model)
    if model is None:
        model = _gateway(context)
    for provider in model.providers:
        context.contribute(RESOURCE_CONTENTS, ResourceContent(provider.ref, provider.content, PROVIDER_MEDIA_TYPE))
    for endpoint in model.endpoints:
        context.contribute(RESOURCE_CONTENTS, ResourceContent(endpoint.ref, endpoint.content, MODEL_BINDING_MEDIA_TYPE))
    return model


def _gateway(context: ModuleContext) -> Model:
    """只有默认网关被采用时读取其配置并编译执行快照。"""
    providers = context.settings.resolve(ProvidersConfig)
    endpoints = context.settings.resolve(EndpointsConfig)
    return LiteLLMModelGateway(
        {item.name: ProviderEndpoint(item.adapter, item.base_url, item.secret_env) for item in providers.providers},
        {item.name: ModelEndpoint(item.provider, item.model) for item in endpoints.endpoints},
    )


MODULE = build

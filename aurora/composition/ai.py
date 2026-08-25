"""构造并导出 ``src.ai`` 的项目 Model 实例。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from aurora.composer import InstanceKey
from aurora.configuration.models import MODELS_CONFIG
from src.ai import LiteLLMModelGateway, ModelEndpoint, ProviderEndpoint
from src.contracts import Model

if TYPE_CHECKING:
    from aurora.composer import CompositionContext

MODEL = InstanceKey[Model]("ai.model")


def register(context: CompositionContext) -> None:
    model = context.model
    if model is None:
        configuration = context.config.get(MODELS_CONFIG)
        model = LiteLLMModelGateway(
            {
                provider_id: ProviderEndpoint(provider.adapter, provider.base_url, provider.secret_env)
                for provider_id, provider in configuration.providers.items()
            },
            {
                endpoint_id: ModelEndpoint(endpoint.provider, endpoint.model)
                for endpoint_id, endpoint in configuration.endpoints.items()
            },
            timeout_seconds=configuration.runtime.attempt_timeout_seconds,
            max_attempts=configuration.runtime.max_attempts,
            total_timeout_seconds=configuration.runtime.total_timeout_seconds,
            max_tokens=configuration.runtime.max_output_tokens,
        )
    context.provide(MODEL, model)

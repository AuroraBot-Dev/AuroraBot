"""登记当前实现的模型协议入口；工厂及实例由装配显式选择。"""

from functools import partial

from aurora_config import ConfigSpec, ConfigTemplate, config_entries
from aurora_core.bootstrap import KindReceiver
from aurora_core.discovery import Plugin
from aurora_core.ids import Id
from aurora_core.registry import RegistryEntry

from .config import ADAPTERS, BINDINGS, BINDINGS_SCHEMA, CONFIG, PROFILE_SCHEMA, ModelAdapter, check_bindings
from .contract import (
    ChatCapabilities,
    ChatChunk,
    ChatClient,
    ChatRequest,
    ChatResponse,
    ChoiceClient,
    EmbeddingClient,
    ModelConfig,
    ModelKind,
)


async def create_client(config: ModelConfig, *, api_key: str | None = None, kind: ModelKind = "chat"):
    """只在实例化时导入 LiteLLM；插件发现与配置解析不创建网络资源。"""
    from .litellm import LiteLLMClient

    return LiteLLMClient(config, api_key=api_key, kind=kind)


def plugin() -> Plugin:
    definitions = (
        ("registries/model/adapters", "registry", KindReceiver(frozenset({"adapter"})), "registries"),
        ("services/model/embedding_client", "service", EmbeddingClient, "services"),
        ("services/model/choice_client", "service", ChoiceClient, "services"),
        ("services/model/chat_client", "service", ChatClient, "services"),
        ("schemas/model/chat/request", "schema", ChatRequest, "schemas"),
        ("schemas/model/chat/response", "schema", ChatResponse, "schemas"),
        ("schemas/model/chat/chunk", "schema", ChatChunk, "schemas"),
        ("schemas/model/chat/capabilities", "schema", ChatCapabilities, "schemas"),
    )
    return Plugin(
        "aurora_adapter.model",
        tuple(
            RegistryEntry(
                Id(f"org.aurora.adapter:{path}"),
                kind,
                target,
                "aurora_adapter.model",
                register_to=Id(f"org.aurora.core:registries/{receiver}"),
            )
            for path, kind, target, receiver in definitions
        )
        + (
            *(
                RegistryEntry(
                    Id(f"org.aurora.adapter:adapters/model/litellm/{kind}"),
                    "adapter",
                    ModelAdapter(kind, partial(create_client, kind=kind)),
                    "aurora_adapter.model",
                    register_to=ADAPTERS,
                )
                for kind in ("chat", "choice", "embedding")
            ),
            *config_entries(
                Id("org.aurora.adapter:configs/model/profiles"),
                ConfigSpec(
                    CONFIG, ConfigTemplate("aurora_adapter", "config.tomls/model/profiles.toml"), PROFILE_SCHEMA
                ),
                provider="aurora_adapter.model",
            ),
            *config_entries(
                Id("org.aurora.adapter:configs/model/bindings"),
                ConfigSpec(
                    BINDINGS,
                    ConfigTemplate("aurora_adapter", "config.tomls/model/bindings.toml"),
                    BINDINGS_SCHEMA,
                    check=check_bindings,
                ),
                provider="aurora_adapter.model",
            ),
        ),
        requires=("aurora_config",),
    )

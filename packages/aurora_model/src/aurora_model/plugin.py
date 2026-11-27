"""模型协议与适配器目录；基础插件不依赖配置包或供应商 SDK。"""

from aurora_core.bootstrap import KindReceiver
from aurora_core.discovery import Plugin
from aurora_core.ids import Id
from aurora_core.registry import RegistryEntry

from .contract import ChatCapabilities, ChatChunk, ChatClient, ChatRequest, ChatResponse, ChoiceClient, EmbeddingClient


def plugin() -> Plugin:
    definitions = (
        ("registries/adapters", "registry", KindReceiver(frozenset({"adapter"})), "registries"),
        ("services/embedding_client", "service", EmbeddingClient, "services"),
        ("services/choice_client", "service", ChoiceClient, "services"),
        ("services/chat_client", "service", ChatClient, "services"),
        ("schemas/chat/request", "schema", ChatRequest, "schemas"),
        ("schemas/chat/response", "schema", ChatResponse, "schemas"),
        ("schemas/chat/chunk", "schema", ChatChunk, "schemas"),
        ("schemas/chat/capabilities", "schema", ChatCapabilities, "schemas"),
    )
    return Plugin(
        "aurora_model",
        tuple(
            RegistryEntry(
                Id(f"org.aurora.model:{path}"),
                kind,
                target,
                "aurora_model",
                register_to=Id(f"org.aurora.core:registries/{receiver}"),
            )
            for path, kind, target, receiver in definitions
        ),
    )

"""模型协议、目录与资源导出；发现阶段不导入供应商 SDK。"""

from aurora_core.bootstrap import KindReceiver
from aurora_core.components import ComponentFactory, InstanceExport

from .contract import ChatCapabilities, ChatChunk, ChatClient, ChatRequest, ChatResponse, ChoiceClient, EmbeddingClient
from .plugins.model._meta import (
    ADAPTERS,
    CHAT_CAPABILITIES,
    CHAT_CHUNK,
    CHAT_CLEAN,
    CHAT_CLIENT,
    CHAT_PREPARE,
    CHAT_REQUEST,
    CHAT_RESPONSE,
    CHOICE_CLEAN,
    CHOICE_CLIENT,
    CHOICE_PREPARE,
    EMBEDDING_CLEAN,
    EMBEDDING_CLIENT,
    EMBEDDING_PREPARE,
    model_plugin,
)
from .resources import ChatResource, ChoiceResource, EmbeddingResource


def _factory(cls, prepare, clean):
    return ComponentFactory(
        cls,
        lambda instance: InstanceExport(
            plugs={prepare: instance.prepare, clean: instance.clean}, resources={"model": instance}
        ),
        plugs=(cls.prepare, cls.clean),
        bind=lambda instance, resources: instance.bind(**resources),
    )


def plugin():
    return model_plugin(
        targets={
            ADAPTERS: KindReceiver(frozenset({"adapter"})),
            CHAT_CLIENT: ChatClient,
            CHOICE_CLIENT: ChoiceClient,
            EMBEDDING_CLIENT: EmbeddingClient,
            CHAT_REQUEST: ChatRequest,
            CHAT_RESPONSE: ChatResponse,
            CHAT_CHUNK: ChatChunk,
            CHAT_CAPABILITIES: ChatCapabilities,
        },
        components={
            "chat": _factory(ChatResource, CHAT_PREPARE, CHAT_CLEAN),
            "choice": _factory(ChoiceResource, CHOICE_PREPARE, CHOICE_CLEAN),
            "embedding": _factory(EmbeddingResource, EMBEDDING_PREPARE, EMBEDDING_CLEAN),
        },
    )

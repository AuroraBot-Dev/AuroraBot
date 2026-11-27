"""LiteLLM 工厂登记；SDK 只在创建客户端时导入。"""

from functools import partial

from aurora_core.discovery import Plugin

from .contract import ModelConfig, ModelKind
from .registry import ModelAdapter


async def create_client(config: ModelConfig, *, api_key: str | None = None, kind: ModelKind = "chat"):
    """创建指定类型的 LiteLLM 客户端。"""
    from .litellm import LiteLLMClient

    return LiteLLMClient(config, api_key=api_key, kind=kind)


def plugin() -> Plugin:
    from .plugins.litellm._meta import CHAT, CHOICE, EMBEDDING, litellm_plugin

    return litellm_plugin(
        targets={
            identity: ModelAdapter(kind, partial(create_client, kind=kind))
            for identity, kind in ((CHAT, "chat"), (CHOICE, "choice"), (EMBEDDING, "embedding"))
        },
        components={},
    )

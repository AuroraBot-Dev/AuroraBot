"""LiteLLM 工厂登记；SDK 只在创建客户端时导入。"""

from functools import partial

from aurora_core.discovery import Plugin
from aurora_core.ids import Id
from aurora_core.registry import RegistryEntry

from .contract import ModelConfig, ModelKind
from .registry import ADAPTERS, ModelAdapter


async def create_client(config: ModelConfig, *, api_key: str | None = None, kind: ModelKind = "chat"):
    """创建指定类型的 LiteLLM 客户端。"""
    from .litellm import LiteLLMClient

    return LiteLLMClient(config, api_key=api_key, kind=kind)


def plugin() -> Plugin:
    return Plugin(
        "aurora_model.litellm",
        tuple(
            RegistryEntry(
                Id(f"org.aurora.model:adapters/litellm/{kind}"),
                "adapter",
                ModelAdapter(kind, partial(create_client, kind=kind)),
                "aurora_model.litellm",
                register_to=ADAPTERS,
            )
            for kind in ("chat", "choice", "embedding")
        ),
        requires=("aurora_model",),
    )

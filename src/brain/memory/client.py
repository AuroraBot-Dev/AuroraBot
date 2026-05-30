from __future__ import annotations

from typing import Any

from mem0 import Memory

from src.brain.ai.providers import resolve_model, setup_providers
from src.config import Config


def _build_vector_store_config() -> dict[str, Any]:
    return {
        "provider": Config.MEMORY_VECTOR_STORE,
        "config": {
            "collection_name": Config.MEMORY_COLLECTION_NAME,
            "path": str(Config.MEMORY_DATA_DIR),
        },
    }


def _build_llm_config(with_model: str = "fast") -> dict[str, Any]:
    if with_model == "fast":
        model = Config.LLM_GATEWAY_FAST_MODEL
    elif with_model == "quality":
        model = Config.LLM_GATEWAY_QUALITY_MODEL
    elif with_model == "multimodal":
        model = Config.LLM_GATEWAY_MULTIMODAL_MODEL
    else:
        raise ValueError(f"Unknown model: {with_model}")  # noqa: TRY003

    return {
        "provider": Config.MEMORY_MODEL_PROVIDER,
        "config": {
            "model": model,
        },
    }


def _build_embedder_config() -> dict[str, Any]:
    setup_providers()
    from src.brain.ai.gateway import get_gateway

    gw = get_gateway()
    embedding_model = gw.embedding

    if "/" not in embedding_model:
        return {
            "provider": "openai",
            "config": {
                "model": embedding_model or "text-embedding-3-small",
            },
        }

    resolved_model, provider_kwargs = resolve_model(embedding_model)

    if "/" in resolved_model:
        _, _, model_name = resolved_model.partition("/")
    else:
        model_name = resolved_model

    embedder_config: dict[str, Any] = {
        "model": model_name,
    }
    if provider_kwargs.get("api_base"):
        embedder_config["openai_base_url"] = provider_kwargs["api_base"]
    if provider_kwargs.get("api_key"):
        embedder_config["api_key"] = provider_kwargs["api_key"]

    return {
        "provider": "openai",
        "config": embedder_config,
    }


def build_memory_config() -> dict[str, Any]:
    return {
        "vector_store": _build_vector_store_config(),
        "llm": _build_llm_config(with_model="fast"),
        "embedder": _build_embedder_config(),
        "history_db_path": str(Config.MEMORY_DATA_DIR / "history.db"),
    }


def create_memory() -> Memory:
    return Memory.from_config(build_memory_config())

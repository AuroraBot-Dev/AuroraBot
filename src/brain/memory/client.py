from __future__ import annotations

from typing import Any

from mem0 import Memory

from src.brain.memory import config


def build_mem0_config() -> dict[str, Any]:
    embedder_api_key = config.MEM0_EMBEDDER_API_KEY.strip()
    if not embedder_api_key:
        raise ValueError(
            "MEM0_EMBEDDER_API_KEY 未配置，无法使用 bge-m3 托管 embedding 接口。"
        )

    llm_api_key = config.MEM0_LLM_API_KEY.strip()
    if not llm_api_key:
        raise ValueError(
            "MEM0_LLM_API_KEY 未配置，无法使用 DeepSeek 作为 mem0 的 LLM。"
        )

    config.MEM0_STORE_PATH.mkdir(parents=True, exist_ok=True)

    return {
        "vector_store": {
            "provider": config.MEM0_VECTOR_STORE,
            "config": {
                "collection_name": config.MEM0_COLLECTION_NAME,
                "path": str(config.MEM0_STORE_PATH),
            },
        },
        "llm": {
            "provider": config.MEM0_LLM_PROVIDER,
            "config": {
                "api_key": llm_api_key,
                "openai_base_url": config.MEM0_LLM_BASE_URL,
                "model": config.MEM0_LLM_MODEL,
            },
        },
        "embedder": {
            "provider": config.MEM0_EMBEDDER_PROVIDER,
            "config": {
                "api_key": embedder_api_key,
                "openai_base_url": config.MEM0_EMBEDDER_BASE_URL,
                "model": config.MEM0_EMBEDDER_MODEL,
            },
        },
    }


def create_memory() -> Memory:
    return Memory.from_config(build_mem0_config())
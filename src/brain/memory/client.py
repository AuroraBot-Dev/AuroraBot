from __future__ import annotations
from typing import Any

from mem0 import Memory
from src.config import Config


def build_memory_config() -> dict[str, Any]:
    return {
        "vector_store": {
            "provider": Config.MEMORY_VECTOR_STORE,
            "config": {
                "collection_name": Config.MEMORY_COLLECTION_NAME,
                "path": str(Config.MEMORY_DATA_DIR),
            },
        },
        "llm": {
            "provider": Config.MEMORY_MODEL_PROVIDER,
            "config": {
                "model": Config.LLM_GATEWAY_FAST_MODEL,
            },
        },
        "embedder": {
            "provider": "openai",
            "config": {
                "api_key": Config.SILICONFLOW_API_KEY,
                "openai_base_url": "https://api.siliconflow.cn/v1",
                "model": "BAAI/bge-m3",
            },
        },
        # "embedder": {
        #     "provider": Config.MEMORY_MODEL_PROVIDER,
        #     "config": {
        #         "model": Config.LLM_GATEWAY_EMBEDDING_MODEL,
        #     },
        # },
        "history_db_path": str(Config.MEMORY_DATA_DIR / "history.db"),
    }


def create_memory() -> Memory:
    return Memory.from_config(build_memory_config())

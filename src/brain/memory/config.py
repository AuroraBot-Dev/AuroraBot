from __future__ import annotations

import os
from pathlib import Path

from src.config import Config as AppConfig

MEM0_VECTOR_STORE: str = os.getenv("MEM0_VECTOR_STORE", "chroma")
MEM0_COLLECTION_NAME: str = os.getenv("MEM0_COLLECTION_NAME", "aurora_memory_bgem3")
MEM0_STORE_PATH: Path = AppConfig.MEMORY_DATA_DIR / "mem0"

MEM0_EMBEDDER_PROVIDER: str = os.getenv("MEM0_EMBEDDER_PROVIDER", "openai")
MEM0_EMBEDDER_API_KEY: str = os.getenv("MEM0_EMBEDDER_API_KEY", "")
MEM0_EMBEDDER_BASE_URL: str = os.getenv(
    "MEM0_EMBEDDER_BASE_URL",
    "https://api.siliconflow.cn/v1",
)
MEM0_EMBEDDER_MODEL: str = os.getenv("MEM0_EMBEDDER_MODEL", "BAAI/bge-m3")

MEM0_LLM_PROVIDER: str = os.getenv("MEM0_LLM_PROVIDER", "openai")
MEM0_LLM_API_KEY: str = os.getenv("MEM0_LLM_API_KEY", AppConfig.DEEPSEEK_API_KEY)
MEM0_LLM_BASE_URL: str = os.getenv("MEM0_LLM_BASE_URL", "https://api.deepseek.com")
MEM0_LLM_MODEL: str = os.getenv("MEM0_LLM_MODEL", "deepseek-chat")
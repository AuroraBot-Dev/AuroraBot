"""从 AuroraConfig 构建 mem0 Memory 配置。"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

    from src.contracts.configuration import AuroraConfig, ModelProviderConfig

_MEMORY_COLLECTION = "aurora_memory"
_DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"

# 已知 Provider 的默认 base_url 映射
_KNOWN_BASE_URLS: dict[str, str] = {
    "deepseek": _DEEPSEEK_BASE_URL,
}


def _resolve_base_url(provider: ModelProviderConfig) -> str | None:
    """解析 Provider 的 base_url：优先使用显式配置，其次查找已知映射。"""
    if provider.base_url is not None:
        return provider.base_url
    return _KNOWN_BASE_URLS.get(provider.id)


def _build_openai_provider_config(role_name: str, config: AuroraConfig) -> dict[str, Any] | None:
    """为给定模型角色构建 OpenAI 兼容的 Provider 配置（LLM 或 Embedder）。"""
    role = config.model_definitions.get(role_name)
    if role is None:
        return None
    provider = config.model_providers.get(role.provider)
    if provider is None:
        return None
    api_key = os.environ.get(provider.secret_env)
    if not api_key:
        return None
    base_url = _resolve_base_url(provider)
    cfg: dict[str, Any] = {"model": role.model, "api_key": api_key}
    if base_url is not None:
        cfg["openai_base_url"] = base_url
    return {"provider": "openai", "config": cfg}


def build_memory_config(config: AuroraConfig, memory_dir: Path) -> dict[str, Any] | None:
    """构建 mem0 记忆系统所需的完整配置，LLM 和 Embedder 均不可用时返回 None。"""
    llm = _build_openai_provider_config("fast", config)
    embedder = _build_openai_provider_config("embedding", config)
    if llm is None or embedder is None:
        return None
    memory_dir.mkdir(parents=True, exist_ok=True)
    return {
        "vector_store": {
            "provider": "chroma",
            "config": {
                "collection_name": _MEMORY_COLLECTION,
                "path": str(memory_dir / "chroma"),
            },
        },
        "llm": llm,
        "embedder": embedder,
        "history_db_path": str(memory_dir / "history.db"),
    }

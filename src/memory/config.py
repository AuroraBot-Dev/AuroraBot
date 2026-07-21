"""Build mem0 Memory configuration from AuroraConfig."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

    from src.contracts.configuration import AuroraConfig, ModelProviderConfig

_MEMORY_COLLECTION = "aurora_memory"
_DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"

_KNOWN_BASE_URLS: dict[str, str] = {
    "deepseek": _DEEPSEEK_BASE_URL,
}


def _resolve_base_url(provider: ModelProviderConfig) -> str | None:
    if provider.base_url is not None:
        return provider.base_url
    return _KNOWN_BASE_URLS.get(provider.id)


def _build_openai_provider_config(role_name: str, config: AuroraConfig) -> dict[str, Any] | None:
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


def build_memory_config(config: AuroraConfig, data_dir: Path) -> dict[str, Any] | None:
    llm = _build_openai_provider_config("fast", config)
    embedder = _build_openai_provider_config("embedding", config)
    if llm is None or embedder is None:
        return None
    memory_dir = data_dir / "memory"
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

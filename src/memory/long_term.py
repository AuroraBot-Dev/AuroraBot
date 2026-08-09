"""长期记忆：mem0。

向量语义检索，embedding 用 embedding role（litellm 同步 embedding）。
mem0 依赖不可用或配置失败时降级为 None（回退 durable_facts 关键词检索）。
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING, Any

from src.utils import get_logger

if TYPE_CHECKING:
    from pathlib import Path

logger = get_logger("aurora.memory.long_term")


class _Msg(StrEnum):
    """本文件内所有用户或模型可见的硬编码文本。"""

    MEM0_UNAVAILABLE = "mem0 不可用，长期记忆降级为 durable_facts 关键词检索"


class LongTermMemory:
    """mem0 长期记忆封装：add 写入向量库，search 语义检索。"""

    def __init__(
        self,
        memory_dir: "Path | None" = None,
        *,
        embed_fn: object | None = None,
        llm_model: str = "deepseek/deepseek-v4-pro",
    ) -> None:
        self._embed_fn = embed_fn
        self._memory = None
        try:
            from mem0 import Memory

            self._memory = Memory.from_config(self._config(memory_dir, llm_model))
        except Exception as error:  # noqa: BLE001
            logger.warning("%s reason=%s", _Msg.MEM0_UNAVAILABLE, type(error).__name__)

    def _config(
        self,
        memory_dir: "Path | None",
        llm_model: str,
    ) -> dict[str, Any]:
        chroma_dir = str(memory_dir / "chroma") if memory_dir is not None else None
        config: dict[str, Any] = {
            "llm": {"provider": "litellm", "config": {"model": llm_model}},
        }
        if self._embed_fn is not None:
            config["embedder"] = {"provider": "custom", "config": {"embedding_func": self._embed_fn}}
        if chroma_dir is not None:
            config["vector_store"] = {
                "provider": "chroma",
                "config": {"collection_name": "aurora_memory", "path": chroma_dir},
            }
        return config

    def add(self, scope: str, text: str, at: str) -> None:
        if self._memory is None:
            return
        try:
            self._memory.add(text, user_id=scope, timestamp=at)
        except Exception as error:  # noqa: BLE001
            logger.warning("mem0 add failed scope=%s error_type=%s", scope, type(error).__name__)

    def search(self, scope: str, query: str, limit: int = 4) -> tuple[str, ...]:
        if self._memory is None:
            return ()
        try:
            results = self._memory.search(query, user_id=scope, top_k=limit)
        except Exception as error:  # noqa: BLE001
            logger.warning("mem0 search failed scope=%s error_type=%s", scope, type(error).__name__)
            return ()
        memories: list[str] = []
        if isinstance(results, dict):
            results = results.get("results", results.get("memories", []))
        if isinstance(results, list):
            for item in results:
                memory = item.get("memory") if isinstance(item, dict) else getattr(item, "memory", None)
                if isinstance(memory, str) and memory.strip():
                    memories.append(memory.strip())
        return tuple(memories[:limit])

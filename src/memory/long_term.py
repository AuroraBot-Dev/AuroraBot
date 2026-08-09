"""长期记忆：mem0。

向量语义检索，embedding 用 embedding role（litellm 同步 embedding）。
mem0 依赖不可用或配置失败时降级为 None（回退 durable_facts 关键词检索）。

mem0 默认把匿名遥测上报 PostHog 云，并在初始化与检索时输出 Chroma 不支持
关键词检索、spaCy 缺失等一次性告知性告警；本模块在导入时禁用遥测
（MEM0_TELEMETRY 可显式开启）并挂接日志过滤器只丢弃这些已知噪音消息。
"""

from __future__ import annotations

import logging
import os
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from src.utils import get_logger

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

logger = get_logger("aurora.memory.long_term")

os.environ.setdefault("MEM0_TELEMETRY", "false")


class _Mem0NoiseFilter(logging.Filter):
    """丢弃 mem0 已知的告知性噪音消息，保留其余告警。

    Chroma 不支持关键词检索与 spaCy 缺失均为一次性告知；语义检索降级为纯向量，
    关键词兜底由 durable facts 关键词排序承担，功能不受影响。
    """

    _NOISE_MARKERS = ("does not support keyword search", "Failed to load spaCy")

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        return not any(marker in message for marker in self._NOISE_MARKERS)


for _mem0_logger_name in ("mem0.memory.main", "mem0.utils.spacy_models"):
    logging.getLogger(_mem0_logger_name).addFilter(_Mem0NoiseFilter())


class _Msg(StrEnum):
    """本文件内所有用户或模型可见的硬编码文本。"""

    MEM0_UNAVAILABLE = "mem0 不可用，长期记忆降级为 durable_facts 关键词检索"
    NOT_CONFIGURED = "未注入 embedding 或聊天模型"


class _GatewayEmbedder:
    """把组合根注入的同步 embedding 函数适配为 mem0 embedder。"""

    def __init__(self, embed_fn: "Callable[[list[str]], list[list[float]]]") -> None:
        self._embed_fn = embed_fn

    def embed(self, text: str, _memory_action: str | None = None) -> list[float]:
        vectors = self._embed_fn([text])
        if len(vectors) != 1 or not vectors[0]:
            raise ValueError("embedding role returned no vector")
        return vectors[0]

    def embed_batch(self, texts: list[str], _memory_action: str = "add") -> list[list[float]]:
        vectors = self._embed_fn(texts)
        if len(vectors) != len(texts) or any(not vector for vector in vectors):
            raise ValueError("embedding role returned an incomplete batch")
        return vectors


class LongTermMemory:
    """mem0 长期记忆封装：add 写入向量库，search 语义检索。"""

    def __init__(
        self,
        memory_dir: "Path | None" = None,
        *,
        embed_fn: "Callable[[list[str]], list[list[float]]] | None" = None,
        llm_model: str | None = None,
    ) -> None:
        self._memory = None
        self._reason: str | None = None
        if memory_dir is None or embed_fn is None or not llm_model:
            self._reason = _Msg.NOT_CONFIGURED
            return
        try:
            from mem0 import Memory

            self._memory = Memory.from_config(self._config(memory_dir, llm_model))
            self._memory.embedding_model = _GatewayEmbedder(embed_fn)
        except Exception as error:  # noqa: BLE001
            self._reason = type(error).__name__
            logger.warning("%s reason=%s", _Msg.MEM0_UNAVAILABLE, type(error).__name__)

    def _config(
        self,
        memory_dir: "Path",
        llm_model: str,
    ) -> dict[str, Any]:
        chroma_dir = str(memory_dir / "chroma")
        config: dict[str, Any] = {
            "llm": {"provider": "litellm", "config": {"model": llm_model}},
            "embedder": {
                "provider": "openai",
                "config": {"model": "aurora-embedding-role", "api_key": "aurora-router"},
            },
            "history_db_path": str(memory_dir / "mem0-history.sqlite3"),
            "vector_store": {
                "provider": "chroma",
                "config": {"collection_name": "aurora_memory", "path": chroma_dir},
            },
        }
        return config

    def status(self) -> dict[str, object]:
        """返回语义记忆是否可用及其降级原因。"""
        return {
            "enabled": self._memory is not None,
            "degraded": self._memory is None or self._reason is not None,
            "reason": self._reason,
        }

    def add(self, scope: str, text: str, at: str) -> None:
        if self._memory is None:
            return
        try:
            self._memory.add(text, user_id=scope, timestamp=at)
        except Exception as error:  # noqa: BLE001
            self._reason = type(error).__name__
            logger.warning("mem0 add failed scope=%s error_type=%s", scope, type(error).__name__)

    def search(self, scope: str, query: str, limit: int = 4) -> tuple[str, ...]:
        if self._memory is None:
            return ()
        try:
            results = self._memory.search(query, filters={"user_id": scope}, top_k=limit)
            self._reason = None
        except Exception as error:  # noqa: BLE001
            self._reason = type(error).__name__
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

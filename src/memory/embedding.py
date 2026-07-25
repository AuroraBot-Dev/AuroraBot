"""嵌入向量生成适配器。

提供统一的文本嵌入接口，当前通过 mem0 内部 OpenAI 兼容 API 实现。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from src.utils.logging import get_logger

logger = get_logger("aurora.memory.embedding")


class _Msg(StrEnum):
    """本文件内所有用户可见或日志输出的字符串常量。"""

    EMBEDDER_NOT_INITIALIZED = "嵌入器尚未初始化"
    EMBED_FAILED = "文本嵌入失败: {error}"
    EMBED_BATCH_FAILED = "批量文本嵌入失败: {error}"


@dataclass(slots=True)
class EmbeddingAdapter:
    """文本嵌入向量生成适配器。

    当前委托 mem0 内部 Embedder 处理，未来可替换为独立实现。
    """

    def __init__(self, config: dict[str, Any]) -> None:
        """使用嵌入配置字典初始化。

        Args:
            config: mem0 Embedder 配置字典。
        """
        self._config = config
        self._embedder: Any = None

    @property
    def embedder(self) -> Any:
        """懒加载 mem0 Embedder 实例。"""
        if self._embedder is None:
            from mem0.embeddings.base import get_embeddings  # type: ignore[import-untyped]

            self._embedder = get_embeddings(self._config)  # type: ignore[no-untyped-call]
        return self._embedder

    def embed(self, text: str) -> list[float]:
        """生成单段文本的嵌入向量。

        Args:
            text: 待向量化的文本。

        Returns:
            list[float]: 嵌入向量。

        Raises:
            RuntimeError: 当嵌入器未初始化时。
        """
        embedder = self.embedder
        if embedder is None:
            raise RuntimeError(_Msg.EMBEDDER_NOT_INITIALIZED)
        try:
            return embedder.embed(text)
        except Exception as error:
            logger.warning(_Msg.EMBED_FAILED.format(error=error))
            raise

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """批量生成嵌入向量。

        Args:
            texts: 待向量化的文本列表。

        Returns:
            list[list[float]]: 嵌入向量列表，与输入顺序一一对应。

        Raises:
            RuntimeError: 当嵌入器未初始化时。
        """
        embedder = self.embedder
        if embedder is None:
            raise RuntimeError(_Msg.EMBEDDER_NOT_INITIALIZED)
        try:
            return embedder.embed_batch(texts)
        except Exception as error:
            logger.warning(_Msg.EMBED_BATCH_FAILED.format(error=error))
            raise

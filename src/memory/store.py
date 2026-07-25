"""mem0 记忆存储封装。

将 mem0 Memory 实例化、配置与基本读写操作封装为独立组件，
供 MemoryService 组合使用。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from src.utils.logging import get_logger

logger = get_logger("aurora.memory.store")


class _Msg(StrEnum):
    """本文件内所有用户可见或日志输出的字符串常量。"""

    MEM0_NOT_INITIALIZED = "mem0 客户端尚未初始化"
    SEARCH_FAILED = "语义搜索失败: {error}"
    ADD_FAILED = "添加记忆失败: {error}"
    ADDED_MEMORY = "已添加记忆: {preview}"


@dataclass(slots=True)
class Mem0Store:
    """mem0 语义记忆存储封装。"""

    def __init__(self, config: dict[str, Any]) -> None:
        """使用 mem0 配置字典初始化存储。

        Args:
            config: mem0 Memory.from_config() 所需的配置字典。
        """
        self._config = config
        self._memory: Any = None

    @property
    def memory(self) -> Any:
        """懒加载 mem0 Memory 实例。"""
        if self._memory is None:
            from mem0 import Memory

            self._memory = Memory.from_config(self._config)
        return self._memory

    def search(self, query: str, user_id: str = "aurora", limit: int = 10) -> list[dict[str, Any]]:
        """语义搜索相关记忆条目。

        Args:
            query: 搜索查询文本。
            user_id: 用户标识符，用于过滤记忆。
            limit: 最大返回结果数。

        Returns:
            list[dict[str, Any]]: 匹配的记忆条目列表，搜索失败时返回空列表。
        """
        if not query.strip():
            return []
        client = self.memory
        if client is None:
            return []
        try:
            hits = client.search(query, filters={"user_id": user_id})
        except (ValueError, KeyError, RuntimeError) as error:
            logger.warning(_Msg.SEARCH_FAILED.format(error=error))
            return []
        if isinstance(hits, dict) and "results" in hits:
            return hits["results"][:limit]
        return []

    def add(
        self,
        content: str | dict[str, Any],
        user_id: str = "aurora",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """添加一条记忆条目到语义记忆库。

        Args:
            content: 记忆内容，可以是字符串或字典形式的对话消息列表。
            user_id: 用户标识符。
            metadata: 可选的附加元数据。

        Raises:
            RuntimeError: 当 mem0 客户端未初始化时。
        """
        client = self.memory
        if client is None:
            raise RuntimeError(_Msg.MEM0_NOT_INITIALIZED)
        messages = [content] if isinstance(content, dict) else [{"role": "user", "content": content}]
        kwargs: dict[str, Any] = {"user_id": user_id}
        if metadata is not None:
            kwargs["metadata"] = metadata
        try:
            client.add(messages, **kwargs)
        except (ValueError, KeyError, RuntimeError) as error:
            logger.warning(_Msg.ADD_FAILED.format(error=error))
            raise
        preview = str(content)[:60]
        logger.debug(_Msg.ADDED_MEMORY.format(preview=preview))

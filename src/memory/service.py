"""自动记忆服务：私有对话账本与 mem0 语义记忆。"""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING, Any

from src.contracts.memory import MemoryContextSnapshot, MemoryConversation, MemoryEntry, MemoryQuery
from src.utils.logging import get_logger

if TYPE_CHECKING:
    from pathlib import Path

    from src.contracts.configuration import AuroraConfig

logger = get_logger("aurora.memory.service")
_DEFAULT_USER_ID = "aurora"


def _build_mem0_config(config: AuroraConfig, memory_dir: Path) -> dict[str, Any] | None:
    """根据应用配置构建 mem0 配置，不可用时返回 None。"""
    from src.memory.config import build_memory_config

    return build_memory_config(config, memory_dir)


class MemoryService:
    """实现 MemoryStore，通过私有账本保证自动写入幂等。"""

    def __init__(self, config: AuroraConfig | None = None, memory_dir: Path | None = None) -> None:
        self._client: Any = None
        self._mem0_config: dict[str, Any] | None = None
        self._user_id = _DEFAULT_USER_ID
        self._memory_dir = memory_dir
        self._ledger_path = memory_dir / "memory.sqlite3" if memory_dir is not None else None
        if config is not None and memory_dir is not None:
            self._mem0_config = _build_mem0_config(config, memory_dir)
        self._available = self._mem0_config is not None
        if self._available:
            logger.info("Memory service initialized data_dir=%s", memory_dir)
        else:
            logger.warning("Memory semantic service unavailable: missing credentials or configuration")

    @classmethod
    def disabled(cls) -> MemoryService:
        """返回不持久化且不调用语义服务的实例。"""
        return cls()

    @property
    def available(self) -> bool:
        """mem0 语义记忆当前是否可用。"""
        return self._available

    @property
    def _mem0(self) -> Any:
        """懒加载 mem0 客户端，初始化失败时停用语义记忆。"""
        if self._client is None and self._mem0_config is not None:
            try:
                from mem0 import Memory

                self._client = Memory.from_config(self._mem0_config)
                logger.info("mem0 client initialized")
            except Exception as error:
                logger.warning("Failed to initialize mem0 client: %s", error)
                self._available = False
                self._mem0_config = None
        return self._client

    def recall(self, query: MemoryQuery) -> MemoryContextSnapshot:
        """为单次 Agent turn 召回对话账本和相关语义记忆。"""
        return MemoryContextSnapshot(
            recent_conversation=self._recent_conversation(
                query.scope,
                limit=query.limit,
                max_characters=query.max_characters,
            ),
            related_memories=tuple(self.search(query.query, limit=5)),
        )

    def remember(self, entry: MemoryEntry) -> bool:
        """幂等记录一条已完成交互，并在可用时同步写入语义记忆。"""
        if self._ledger_path is None or not entry.user.strip():
            return False
        assert self._memory_dir is not None
        self._memory_dir.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            cursor = connection.execute(
                "INSERT OR IGNORE INTO completed_tasks"
                "(task_id, scope, user_text, assistant_text, created_at) VALUES (?, ?, ?, ?, ?)",
                (entry.task_id, entry.scope, entry.user, entry.assistant, entry.created_at),
            )
            inserted = cursor.rowcount > 0
        if not inserted:
            return False
        content = f"用户：{entry.user}"
        if entry.assistant is not None and entry.assistant.strip():
            content += f"\nAurora：{entry.assistant.strip()}"
        if self._available and not self.add(content):
            with self._connect() as connection:
                connection.execute("DELETE FROM completed_tasks WHERE task_id = ?", (entry.task_id,))
            return False
        return True

    def search(self, query: str, user_id: str | None = None, limit: int = 8) -> list[str]:
        """语义搜索记忆库，返回匹配文本列表。"""
        if not self._available or not query.strip():
            return []
        client = self._mem0
        if client is None:
            return []
        try:
            hits = client.search(query, filters={"user_id": user_id or self._user_id})
        except Exception as error:
            logger.warning("mem0 search failed: %s", error)
            return []
        if isinstance(hits, dict) and "results" in hits:
            results = [hit["memory"] for hit in hits["results"] if isinstance(hit, dict) and "memory" in hit]
            return results[:limit]
        return []

    def add(self, content: str, user_id: str | None = None) -> bool:
        """向语义记忆库添加一条新记忆。"""
        if not self._available or not content.strip():
            return False
        client = self._mem0
        if client is None:
            return False
        try:
            client.add([{"role": "user", "content": content}], user_id=user_id or self._user_id)
        except Exception as error:
            logger.warning("mem0 add failed: %s", error)
            return False
        logger.debug("Added to memory: %s...", content[:60])
        return True

    def _connect(self) -> sqlite3.Connection:
        """打开记忆私有账本并确保 schema 已初始化。"""
        assert self._ledger_path is not None
        connection = sqlite3.connect(str(self._ledger_path))
        connection.execute(
            "CREATE TABLE IF NOT EXISTS completed_tasks("
            "task_id TEXT PRIMARY KEY, scope TEXT NOT NULL, user_text TEXT NOT NULL, "
            "assistant_text TEXT, created_at TEXT NOT NULL)"
        )
        columns = {str(row[1]) for row in connection.execute("PRAGMA table_info(completed_tasks)")}
        if "scope" not in columns:
            connection.execute("ALTER TABLE completed_tasks ADD COLUMN scope TEXT NOT NULL DEFAULT 'global'")
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_completed_tasks_scope_created ON completed_tasks(scope, created_at DESC)"
        )
        return connection

    def _recent_conversation(
        self,
        scope: str,
        *,
        limit: int,
        max_characters: int,
    ) -> tuple[MemoryConversation, ...]:
        """从记忆私有账本读取最近的已完成对话。"""
        if self._ledger_path is None or not self._ledger_path.exists():
            return ()
        try:
            with self._connect() as connection:
                rows = connection.execute(
                    "SELECT user_text, assistant_text FROM completed_tasks "
                    "WHERE scope = ? ORDER BY created_at DESC LIMIT ?",
                    (scope, limit),
                ).fetchall()
        except sqlite3.Error as error:
            logger.warning("memory conversation recall failed: %s", error)
            return ()
        selected: list[MemoryConversation] = []
        remaining = max_characters
        for user, assistant in rows:
            if remaining <= 0:
                break
            user_text = str(user)
            assistant_text = str(assistant) if assistant is not None else None
            combined = len(user_text) + len(assistant_text or "")
            if combined <= remaining:
                selected.append(MemoryConversation(user_text, assistant_text))
                remaining -= combined
                continue
            clipped_user = _clip(user_text, remaining)
            remaining -= len(clipped_user)
            clipped_assistant = _clip(assistant_text or "", remaining) if remaining > 0 else ""
            if clipped_user or clipped_assistant:
                selected.append(MemoryConversation(clipped_user, clipped_assistant or None))
            break
        return tuple(reversed(selected))


def _clip(value: str, limit: int) -> str:
    if limit <= 0:
        return ""
    if len(value) <= limit:
        return value
    if limit == 1:
        return "…"
    return f"{value[: limit - 1]}…"

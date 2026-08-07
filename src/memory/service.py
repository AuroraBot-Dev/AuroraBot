"""有界会话摘要与长期事实的轻量 SQLite 实现。"""

from __future__ import annotations

import sqlite3
from enum import StrEnum
from typing import TYPE_CHECKING

from src.contracts import (
    MemoryContextSnapshot,
    MemoryEntry,
    MemoryQuery,
)
from src.utils import get_logger

if TYPE_CHECKING:
    from pathlib import Path

logger = get_logger("aurora.memory.service")
_SUMMARY_LIMIT = 2400


class _Msg(StrEnum):
    """本文件内所有用户或模型可见的硬编码文本。"""

    ELLIPSIS = "…"
    REMEMBERED_TURN = "{input_summary}\nAurora：{outcome_summary}"


class MemoryService:
    """只保存压缩投影，不保存原始对话副本或向量数据库。"""

    def __init__(self, memory_dir: Path | None = None) -> None:
        self._memory_dir = memory_dir
        self._database_path = memory_dir / "memory.sqlite3" if memory_dir is not None else None
        if memory_dir is not None:
            memory_dir.mkdir(parents=True, exist_ok=True)
            with self._connect() as connection:
                self._initialize(connection)

    def recall(self, query: MemoryQuery) -> MemoryContextSnapshot:
        if self._database_path is None:
            return MemoryContextSnapshot()
        try:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT summary FROM session_memory WHERE scope = ?",
                    (query.scope,),
                ).fetchone()
                summary = str(row[0]) if row is not None else ""
                facts = self._select_facts(connection, query)
        except sqlite3.Error as error:
            logger.warning("Memory recall failed error=%s", error)
            return MemoryContextSnapshot()
        summary = _clip(summary, query.max_characters)
        remaining = max(0, query.max_characters - len(summary))
        selected: list[str] = []
        for fact in facts:
            clipped = _clip(fact, remaining)
            if not clipped:
                break
            selected.append(clipped)
            remaining -= len(clipped)
        return MemoryContextSnapshot(summary, tuple(selected))

    def remember(self, entry: MemoryEntry) -> bool:
        if self._database_path is None or not entry.input_summary.strip():
            return False
        with self._connect() as connection:
            cursor = connection.execute(
                "INSERT OR IGNORE INTO memory_receipts(task_id, scope, created_at) VALUES (?, ?, ?)",
                (entry.task_id, entry.scope, entry.created_at),
            )
            if cursor.rowcount == 0:
                return False
            previous = connection.execute(
                "SELECT summary FROM session_memory WHERE scope = ?",
                (entry.scope,),
            ).fetchone()
            turn = entry.input_summary.strip()
            if entry.outcome_summary and entry.outcome_summary.strip():
                turn = _Msg.REMEMBERED_TURN.format(
                    input_summary=turn,
                    outcome_summary=entry.outcome_summary.strip(),
                )
            combined = f"{previous[0]}\n{turn}".strip() if previous is not None else turn
            summary = _tail(combined, _SUMMARY_LIMIT)
            connection.execute(
                "INSERT INTO session_memory(scope, summary, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(scope) DO UPDATE SET summary=excluded.summary, updated_at=excluded.updated_at",
                (entry.scope, summary, entry.created_at),
            )
            for candidate in entry.fact_candidates:
                fact = candidate.strip()
                if fact:
                    connection.execute(
                        "INSERT OR IGNORE INTO durable_facts(scope, content, source_task_id, created_at) "
                        "VALUES (?, ?, ?, ?)",
                        (entry.scope, _clip(fact, 500), entry.task_id, entry.created_at),
                    )
        return True

    def _select_facts(self, connection: sqlite3.Connection, query: MemoryQuery) -> tuple[str, ...]:
        rows = connection.execute(
            "SELECT content FROM durable_facts WHERE scope IN (?, 'global') ORDER BY created_at DESC LIMIT ?",
            (query.scope, max(query.fact_limit * 4, query.fact_limit)),
        ).fetchall()
        terms = {term.casefold() for term in query.query.split() if len(term) > 1}
        ranked = sorted(
            (str(row[0]) for row in rows),
            key=lambda value: sum(term in value.casefold() for term in terms),
            reverse=True,
        )
        return tuple(ranked[: query.fact_limit])

    def _connect(self) -> sqlite3.Connection:
        assert self._database_path is not None
        return sqlite3.connect(self._database_path, timeout=30)

    @staticmethod
    def _initialize(connection: sqlite3.Connection) -> None:
        connection.executescript(
            "PRAGMA journal_mode=WAL;"
            "PRAGMA journal_size_limit=524288;"
            "DROP TABLE IF EXISTS completed_tasks;"
            "CREATE TABLE IF NOT EXISTS memory_receipts("
            "task_id TEXT PRIMARY KEY, scope TEXT NOT NULL, created_at TEXT NOT NULL);"
            "CREATE TABLE IF NOT EXISTS session_memory("
            "scope TEXT PRIMARY KEY, summary TEXT NOT NULL, updated_at TEXT NOT NULL);"
            "CREATE TABLE IF NOT EXISTS durable_facts("
            "fact_id INTEGER PRIMARY KEY, scope TEXT NOT NULL, content TEXT NOT NULL, "
            "source_task_id TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(scope, content));"
            "CREATE INDEX IF NOT EXISTS idx_durable_facts_scope_created "
            "ON durable_facts(scope, created_at DESC);"
        )


def _clip(value: str, limit: int) -> str:
    if limit <= 0:
        return ""
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 1)] + _Msg.ELLIPSIS


def _tail(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return _Msg.ELLIPSIS + value[-(limit - 1) :]

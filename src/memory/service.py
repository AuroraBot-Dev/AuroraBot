"""记忆引擎（RFC 0216）：短期窗口 + LLM 概要，长期 durable_facts（mem0 可选）。

分层：
- ``memory_messages``：最近 N 条原始消息（窗口）；
- ``session_memory``：窗口外压缩概要（LLM 生成，fast role）；
- ``durable_facts``：长期事实（mem0 不可用时降级的关键词检索）。
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Protocol

from src.contracts import (
    MemoryContextSnapshot,
    MemoryEntry,
    MemoryMessage,
    MemoryQuery,
)
from src.utils import get_logger


class _Summarizer(Protocol):
    """概要生成所需的网关窄面（避免 memory 依赖 ai 包，RFC 0200 边界）。"""

    async def get_response(self, role: str, inputs: list[dict]) -> dict[str, Any]: ...


if TYPE_CHECKING:
    from pathlib import Path

logger = get_logger("aurora.memory.service")
_SUMMARY_LIMIT = 2400
_DEFAULT_WINDOW_MIN = 100
_DEFAULT_WINDOW_MAX = 300


class _Msg(StrEnum):
    """本文件内所有用户或模型可见的硬编码文本。"""

    ELLIPSIS = "…"
    SUMMARIZE_PROMPT = (
        "你负责记忆浓缩：把『最早记忆项』与一批旧对话再次压缩为一条更浓缩的"
        "记忆项（保留关键事实，丢弃已失去时效的细节）。\n"
        "最早记忆项：\n{summary}\n\n旧对话：\n{messages}\n\n只输出新的记忆项文本。"
    )


class MemoryService:
    """短期记忆（窗口+概要）+ 长期事实（可选 mem0）的组合实现。"""

    def __init__(
        self,
        memory_dir: "Path | None" = None,
        *,
        gateway: _Summarizer | None = None,
        window_min: int = _DEFAULT_WINDOW_MIN,
        window_max: int = _DEFAULT_WINDOW_MAX,
    ) -> None:
        self._memory_dir = memory_dir
        self._gateway: _Summarizer | None = gateway
        self._window_min = window_min
        self._window_max = window_max
        self._database_path = memory_dir / "memory.sqlite3" if memory_dir is not None else None
        if memory_dir is not None:
            memory_dir.mkdir(parents=True, exist_ok=True)
            with self._connect() as connection:
                self._initialize(connection)
        from src.memory.long_term import LongTermMemory

        self._long_term = LongTermMemory(memory_dir) if memory_dir is not None else None

    def recall(self, query: MemoryQuery) -> MemoryContextSnapshot:
        if self._database_path is None:
            return MemoryContextSnapshot()
        try:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT summary FROM session_memory WHERE scope = ?", (query.scope,)
                ).fetchone()
                summary = str(row[0]) if row is not None else ""
                rows = connection.execute(
                    "SELECT role, content, at FROM memory_messages WHERE scope = ? ORDER BY seq DESC LIMIT ?",
                    (query.scope, self._window_max),
                ).fetchall()
                window = tuple(
                    MemoryMessage(str(row["role"]), str(row["content"]), str(row["at"])) for row in reversed(rows)
                )
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
        return MemoryContextSnapshot(summary, window, tuple(selected))

    def append_turn(self, scope: str, *, role: str, content: str, at: str) -> None:
        """把一轮对话追加进窗口；溢出时把最旧消息浓缩进概要（LLM 摘要）。"""
        if self._database_path is None or not content.strip():
            return
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO memory_messages(scope, role, content, at) VALUES (?, ?, ?, ?)",
                (scope, role, content, at),
            )
            count = int(
                connection.execute("SELECT count(*) FROM memory_messages WHERE scope = ?", (scope,)).fetchone()[0]
            )
            if count > self._window_max:
                self._condense(connection, scope, count - self._window_min)

    def remember(self, entry: MemoryEntry) -> bool:
        """终态投影：幂等回执 + 长期事实（窗口消息由 append_turn 负责）。"""
        if self._database_path is None or not entry.input_summary.strip():
            return False
        with self._connect() as connection:
            cursor = connection.execute(
                "INSERT OR IGNORE INTO memory_receipts(task_id, scope, created_at) VALUES (?, ?, ?)",
                (entry.task_id, entry.scope, entry.created_at),
            )
            if cursor.rowcount == 0:
                return False
            for candidate in entry.fact_candidates:
                fact = candidate.strip()
                if fact:
                    connection.execute(
                        "INSERT OR IGNORE INTO durable_facts(scope, content, source_task_id, created_at) "
                        "VALUES (?, ?, ?, ?)",
                        (entry.scope, _clip(fact, 500), entry.task_id, entry.created_at),
                    )
        if self._long_term is not None and entry.outcome_summary:
            self._long_term.add(entry.scope, f"{entry.input_summary}\n{entry.outcome_summary}", entry.created_at)
        return True

    def _condense(self, connection: sqlite3.Connection, scope: str, excess: int) -> None:
        """把最旧 ``excess`` 条消息 + 现有概要浓缩为新概要（LLM 或规则截断）。"""
        rows = connection.execute(
            "SELECT role, content, at FROM memory_messages WHERE scope = ? ORDER BY seq ASC LIMIT ?",
            (scope, excess),
        ).fetchall()
        if not rows:
            return
        existing = connection.execute("SELECT summary FROM session_memory WHERE scope = ?", (scope,)).fetchone()
        summary = str(existing[0]) if existing else ""
        oldest = [{"role": str(row["role"]), "content": str(row["content"]), "at": str(row["at"])} for row in rows]
        condensed = self._summarize(summary, oldest)
        connection.execute(
            "INSERT INTO session_memory(scope, summary, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(scope) DO UPDATE SET summary=excluded.summary, updated_at=excluded.updated_at",
            (scope, condensed, datetime.now(UTC).isoformat()),
        )
        connection.execute(
            "DELETE FROM memory_messages WHERE scope = ? AND rowid IN ("
            "SELECT rowid FROM memory_messages WHERE scope = ? ORDER BY seq ASC LIMIT ?)",
            (scope, scope, excess),
        )

    def _summarize(self, existing: str, messages: list[dict[str, Any]]) -> str:
        """LLM 浓缩（fast role）；网关不可用时规则截断。"""
        if self._gateway is None:
            combined = existing + "\n" + "\n".join(m["content"] for m in messages)
            return _tail(combined.strip(), _SUMMARY_LIMIT)
        import asyncio

        assert self._gateway is not None
        prompt = _Msg.SUMMARIZE_PROMPT.format(
            summary=existing or "（无）",
            messages="\n".join(f"{m['role']}: {m['content']}" for m in messages),
        )
        try:
            result = asyncio.run(self._gateway.get_response("fast", [{"role": "user", "content": prompt}]))
            text = str(result.get("text", "")).strip()
            if text:
                return _tail(text, _SUMMARY_LIMIT)
        except Exception as error:
            logger.warning("memory summarization failed error_type=%s", type(error).__name__)
        combined = existing + "\n" + "\n".join(m["content"] for m in messages)
        return _tail(combined.strip(), _SUMMARY_LIMIT)

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
        connection = sqlite3.connect(self._database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        return connection

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
            "CREATE TABLE IF NOT EXISTS memory_messages("
            "seq INTEGER PRIMARY KEY AUTOINCREMENT, scope TEXT NOT NULL, role TEXT NOT NULL, "
            "content TEXT NOT NULL, at TEXT NOT NULL);"
            "CREATE INDEX IF NOT EXISTS idx_memory_messages_scope "
            "ON memory_messages(scope, seq);"
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

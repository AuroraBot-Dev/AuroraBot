"""Memory service wrapping mem0 for semantic search and SQLite for episodic recall."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.contracts.configuration import AuroraConfig

from src.utils.log_utils import get_logger

logger = get_logger("aurora.memory.service")

_DEFAULT_USER_ID = "aurora"
_DATA_SUBDIR = "memory"


def _build_mem0_config(config: AuroraConfig, data_dir: Path) -> dict[str, Any] | None:
    from src.memory.config import build_memory_config as build

    return build(config, data_dir)


class MemoryService:
    """Direct memory service: reads L2/L3 automatically, writes via tool delegation."""

    def __init__(
        self,
        config: AuroraConfig | None = None,
        data_dir: Path | None = None,
        workspace: Path | None = None,
    ) -> None:
        self._client: Any = None
        self._mem0_config: dict[str, Any] | None = None
        self._user_id = _DEFAULT_USER_ID
        if config is None or data_dir is None or workspace is None:
            self._available = False
            self._db_path = Path(":memory:")
            return
        self._mem0_config = _build_mem0_config(config, data_dir)
        self._db_path = workspace / "process" / "runtime.sqlite3"
        self._available = self._mem0_config is not None
        if self._available:
            logger.info("Memory service initialized data_dir=%s", data_dir / _DATA_SUBDIR)
        else:
            logger.warning("Memory service unavailable: missing credentials or configuration")

    @classmethod
    def disabled(cls) -> MemoryService:
        return cls()

    @property
    def available(self) -> bool:
        return self._available

    @property
    def _mem0(self) -> Any:
        if self._client is None and self._mem0_config is not None:
            try:
                from mem0 import Memory

                self._client = Memory.from_config(self._mem0_config)
                logger.info("mem0 client initialized")
            except Exception as exc:
                logger.warning("Failed to initialize mem0 client: %s", exc)
                self._available = False
                self._mem0_config = None
        return self._client

    def search(self, query: str, user_id: str | None = None, limit: int = 8) -> list[str]:
        if not self._available or not query.strip():
            return []
        client = self._mem0
        if client is None:
            return []
        uid = user_id or self._user_id
        try:
            hits = client.search(query, filters={"user_id": uid})
        except Exception as exc:
            logger.warning("mem0 search failed: %s", exc)
            return []
        if isinstance(hits, dict) and "results" in hits:
            results = [hit["memory"] for hit in hits["results"] if isinstance(hit, dict) and "memory" in hit]
            return results[:limit]
        return []

    def add(self, content: str, user_id: str | None = None) -> bool:
        if not self._available or not content.strip():
            return False
        client = self._mem0
        if client is None:
            return False
        uid = user_id or self._user_id
        try:
            client.add([{"role": "user", "content": content}], user_id=uid)
        except Exception as exc:
            logger.warning("mem0 add failed: %s", exc)
            return False
        else:
            logger.debug("Added to memory: %s...", content[:60])
            return True

    def recall_recent_events(self, limit: int = 10) -> list[dict[str, str]]:
        if not self._db_path.exists():
            return []
        conn = None
        try:
            conn = sqlite3.connect(str(self._db_path))
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT type, summary, created_at FROM causal_events ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [{"type": row["type"], "summary": row["summary"], "created_at": row["created_at"]} for row in rows]
        except Exception:
            logger.warning("recall_recent_events failed")
            return []
        finally:
            if conn is not None:
                conn.close()

    def recall_conversation(self, limit: int = 8) -> list[dict[str, str | None]]:
        if not self._db_path.exists():
            return []
        conn = None
        try:
            conn = sqlite3.connect(str(self._db_path))
            conn.row_factory = sqlite3.Row
            started = {
                row["task_id"]: row["summary"]
                for row in conn.execute(
                    "SELECT task_id, summary FROM causal_events "
                    "WHERE type = 'task.started' AND summary != 'system.tick' "
                    "ORDER BY created_at DESC LIMIT ?",
                    (limit * 2,),
                ).fetchall()
            }
            if not started:
                return []
            placeholders = ",".join("?" for _ in started)
            rows = conn.execute(
                f"SELECT task_id, summary FROM causal_events "
                f"WHERE type = 'agent.complete' AND task_id IN ({placeholders}) "
                f"ORDER BY created_at ASC",
                tuple(started.keys()),
            ).fetchall()
            completed: dict[str, str] = {}
            for row in rows:
                summary = row["summary"]
                if isinstance(summary, str) and summary.strip():
                    completed[row["task_id"]] = summary
            conversation: list[dict[str, str | None]] = []
            for task_id, user_msg in started.items():
                turn: dict[str, str | None] = {"user": user_msg}
                turn["bot"] = completed.get(task_id)
                conversation.append(turn)
            conversation.reverse()
            return conversation[-limit:]
        except Exception:
            logger.warning("recall_conversation failed")
            return []
        finally:
            if conn is not None:
                conn.close()

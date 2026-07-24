"""记忆服务：包装 mem0 语义搜索和 SQLite 情景回忆。"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.contracts.configuration import AuroraConfig

from src.utils.logging import get_logger

logger = get_logger("aurora.memory.service")

_DEFAULT_USER_ID = "aurora"
_DATA_SUBDIR = "memory"


def _build_mem0_config(config: AuroraConfig, data_dir: Path) -> dict[str, Any] | None:
    """根据应用配置构建 mem0 记忆系统配置，不可用时返回 None。"""
    from src.memory.config import build_memory_config as build

    return build(config, data_dir)


class MemoryService:
    """直接记忆服务：读取 L2/L3 由服务自动完成，写入通过工具委派。"""

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
            # 未提供完整配置时处于禁用状态
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
        """返回一个已禁用的记忆服务实例（用于无记忆场景）。"""
        return cls()

    @property
    def available(self) -> bool:
        """记忆服务当前是否可用。"""
        return self._available

    @property
    def _mem0(self) -> Any:
        """懒加载 mem0 Memory 客户端，初始化失败则标记为不可用。"""
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
        """语义搜索记忆库，返回匹配文本列表。"""
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
        """向记忆库添加一条新记忆（由工具委派写入）。"""
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
        """从因果事件表中召回最近的事件记录。"""
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
        """从因果事件表中重建最近对话（用户消息→Aurora 回复）。"""
        if not self._db_path.exists():
            return []
        conn = None
        try:
            conn = sqlite3.connect(str(self._db_path))
            conn.row_factory = sqlite3.Row
            # 先获取最近启动的 Task（排除自主心跳）
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
            # 按时间倒序组装对话轮次
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

    def auto_remember_completed_tasks(self) -> int:
        """从因果事件表中自动提取最近完成的交互并写入记忆，返回已记忆条数。"""
        if not self._available or not self._db_path.exists():
            return 0
        conn = None
        try:
            conn = sqlite3.connect(str(self._db_path))
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT e1.task_id, e1.summary AS user_msg, e2.summary AS bot_msg "
                "FROM causal_events e1 "
                "LEFT JOIN causal_events e2 ON e1.task_id = e2.task_id AND e2.type = 'agent.complete' "
                "WHERE e1.type = 'task.started' AND e1.summary != 'system.tick' "
                "ORDER BY e1.created_at DESC LIMIT 6"
            ).fetchall()
        except Exception:
            logger.warning("auto_remember_completed_tasks query failed")
            return 0
        finally:
            if conn is not None:
                conn.close()
        remembered = 0
        for row in rows:
            user_msg = row["user_msg"]
            bot_msg = row["bot_msg"]
            if not isinstance(user_msg, str) or not user_msg.strip():
                continue
            content = f"用户：{user_msg}"
            if isinstance(bot_msg, str) and bot_msg.strip():
                stripped = bot_msg.strip()
                # 跳过纯结构化工具操作摘要
                if stripped.startswith("{") and '"operation"' in stripped:
                    continue
                content += f"\nAurora：{stripped}"
            if self.add(content):
                remembered += 1
        if remembered:
            logger.debug("auto-remembered %d completed tasks", remembered)
        return remembered

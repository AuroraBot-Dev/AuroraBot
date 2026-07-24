"""只读 Task、Agent、因果事件与情境查询。

提供所有无需事务边界的读取操作，包括聚合计数、
Agent 子列表、消息查询、因果事件回溯等。
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from src.contracts.agent import AgentInstance, TaskState
from src.engine.store_base import RuntimeStoreBase, _json, utc_now


class StoreQueriesMixin(RuntimeStoreBase):
    """只读查询 Mixin，不产生写事务。"""

    def get_task(self, task_id: str) -> TaskState | None:
        """按 task_id 查找 Task。不存在时返回 None。"""
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
            return self._task(row) if row is not None else None

    def get_agent(self, agent_id: str) -> AgentInstance | None:
        """按 agent_id 查找 Agent。不存在时返回 None。"""
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM agents WHERE agent_id = ?", (agent_id,)).fetchone()
            return self._agent(row) if row is not None else None

    def children(self, agent_id: str) -> tuple[AgentInstance, ...]:
        """返回指定 Agent 的所有子 Agent（按创建时间排序）。"""
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM agents WHERE parent_agent_id = ? ORDER BY created_at, agent_id", (agent_id,)
            ).fetchall()
            return tuple(self._agent(row) for row in rows)

    def tasks(self, *, active_only: bool = False) -> tuple[TaskState, ...]:
        """返回所有 Task。active_only=True 时仅返回 ACTIVE 状态的 Task。"""
        query = "SELECT * FROM tasks"
        if active_only:
            query += " WHERE status = 'ACTIVE'"
        query += " ORDER BY started_at, task_id"
        with self.connect() as connection:
            return tuple(self._task(row) for row in connection.execute(query).fetchall())

    def agents(self, *, active_only: bool = False) -> tuple[AgentInstance, ...]:
        """返回所有 Agent。active_only=True 时排除 COMPLETED/FAILED/CANCELLED。"""
        query = "SELECT * FROM agents"
        if active_only:
            query += " WHERE status NOT IN ('COMPLETED', 'FAILED', 'CANCELLED')"
        query += " ORDER BY created_at, agent_id"
        with self.connect() as connection:
            return tuple(self._agent(row) for row in connection.execute(query).fetchall())

    def messages_for_agent(self, agent_id: str) -> tuple[dict[str, Any], ...]:
        """返回指定 Agent 的所有邮箱消息（按创建时间排序）。"""
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM mailbox WHERE target_agent_id = ? ORDER BY created_at, message_id", (agent_id,)
            ).fetchall()
            return tuple(self._message(row).to_dict() for row in rows)

    def has_pending_child_reports(self, agent_id: str) -> bool:
        """检查 Agent 是否有尚未处理的子 Agent 完成/失败报告。"""
        with self.connect() as connection:
            return bool(
                connection.execute(
                    "SELECT 1 FROM mailbox WHERE target_agent_id = ? AND type IN ('child.completed', 'child.failed') "
                    "AND status = 'PENDING' LIMIT 1",
                    (agent_id,),
                ).fetchone()
            )

    def events_for_task(self, task_id: str) -> tuple[dict[str, Any], ...]:
        """返回指定 Task 的所有因果事件（按创建时间排序）。用于调试和审计回溯。"""
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM causal_events WHERE task_id = ? ORDER BY created_at, event_id", (task_id,)
            ).fetchall()
            return tuple(
                {
                    "event_id": row["event_id"],
                    "task_id": row["task_id"],
                    "agent_id": row["agent_id"],
                    "type": row["type"],
                    "summary": row["summary"],
                    "payload": json.loads(row["payload_json"]),
                    "causation_id": row["causation_id"],
                    "correlation_id": row["correlation_id"],
                    "created_at": row["created_at"],
                }
                for row in rows
            )

    def situations(self) -> tuple[dict[str, Any], ...]:
        """返回所有未过期且未认领的情境（OPEN 状态，优先级降序）。"""
        now = utc_now()
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM situations WHERE status = 'OPEN' AND expires_at > ? ORDER BY priority DESC, created_at",
                (now,),
            ).fetchall()
            return tuple(
                {
                    "situation_id": row["situation_id"],
                    "source": row["source"],
                    "type": row["type"],
                    "summary": row["summary"],
                    "payload": json.loads(row["payload_json"]),
                    "priority": row["priority"],
                    "expires_at": row["expires_at"],
                    "created_at": row["created_at"],
                }
                for row in rows
            )

    def expire_situations(self) -> None:
        """将已过期的 OPEN 情境标记为 EXPIRED。应在每个 pump 周期调用。"""
        now = utc_now()
        with self.transaction() as connection:
            connection.execute(
                "UPDATE situations SET status = 'EXPIRED', updated_at = ? WHERE status = 'OPEN' AND expires_at <= ?",
                (now, now),
            )

    def add_situation(
        self,
        source: str,
        event_type: str,
        summary: str,
        payload: dict[str, Any],
        priority: int,
        ttl_seconds: float,
    ) -> str:
        """创建一条新情境记录并返回其 situation_id。过期时间为创建时间 + ttl_seconds。"""
        now_dt = datetime.now(UTC)
        situation_id = str(uuid4())
        with self.transaction() as connection:
            connection.execute(
                "INSERT INTO situations (situation_id, audience_ref, source, type, summary, payload_json, priority, "
                "status, claimed_by_agent_id, expires_at, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, 'OPEN', NULL, ?, ?, ?)",
                (
                    situation_id,
                    "global",
                    source,
                    event_type,
                    summary,
                    _json(payload),
                    priority,
                    (now_dt + timedelta(seconds=ttl_seconds)).isoformat(),
                    now_dt.isoformat(),
                    now_dt.isoformat(),
                ),
            )
        return situation_id

    def counts(self) -> dict[str, int]:
        """返回运行时仓库的关键聚合计数。用于监控和 has_work 判断。"""
        with self.connect() as connection:
            return {
                "active_tasks": int(
                    connection.execute("SELECT count(*) FROM tasks WHERE status = 'ACTIVE'").fetchone()[0]
                ),
                "active_agents": int(
                    connection.execute(
                        "SELECT count(*) FROM agents WHERE status NOT IN ('COMPLETED', 'FAILED', 'CANCELLED')"
                    ).fetchone()[0]
                ),
                "pending_messages": int(
                    connection.execute("SELECT count(*) FROM mailbox WHERE status = 'PENDING'").fetchone()[0]
                ),
                "processing_messages": int(
                    connection.execute("SELECT count(*) FROM mailbox WHERE status = 'PROCESSING'").fetchone()[0]
                ),
                "pending_activities": int(
                    connection.execute("SELECT count(*) FROM activities WHERE status = 'PENDING'").fetchone()[0]
                ),
                "pending_model_activities": int(
                    connection.execute(
                        "SELECT count(*) FROM activities WHERE kind = 'model' AND status = 'PENDING'"
                    ).fetchone()[0]
                ),
                "processing_model_activities": int(
                    connection.execute(
                        "SELECT count(*) FROM activities WHERE kind = 'model' AND status = 'PROCESSING'"
                    ).fetchone()[0]
                ),
                "pending_tool_activities": int(
                    connection.execute(
                        "SELECT count(*) FROM activities WHERE kind = 'tool' AND status = 'PENDING'"
                    ).fetchone()[0]
                ),
                "processing_tool_activities": int(
                    connection.execute(
                        "SELECT count(*) FROM activities WHERE kind = 'tool' AND status = 'PROCESSING'"
                    ).fetchone()[0]
                ),
            }

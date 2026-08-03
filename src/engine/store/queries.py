"""Task、Agent、因果事件与运行计数查询。"""

from __future__ import annotations

import json
from typing import Any

from src.contracts.agent import AgentInstance, TaskState

from .base import RuntimeStoreBase, utc_now


class StoreQueriesMixin(RuntimeStoreBase):
    """运行态只读查询。"""

    def get_task(self, task_id: str) -> TaskState | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
            return self._task(row) if row is not None else None

    def get_agent(self, agent_id: str) -> AgentInstance | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM agents WHERE agent_id = ?", (agent_id,)).fetchone()
            return self._agent(row) if row is not None else None

    def children(self, agent_id: str) -> tuple[AgentInstance, ...]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM agents WHERE parent_agent_id = ? ORDER BY created_at, agent_id", (agent_id,)
            ).fetchall()
            return tuple(self._agent(row) for row in rows)

    def tasks(self, *, active_only: bool = False) -> tuple[TaskState, ...]:
        query = "SELECT * FROM tasks"
        if active_only:
            query += " WHERE status = 'ACTIVE'"
        query += " ORDER BY started_at, task_id"
        with self.connect() as connection:
            return tuple(self._task(row) for row in connection.execute(query).fetchall())

    def agents(self, *, active_only: bool = False) -> tuple[AgentInstance, ...]:
        query = "SELECT * FROM agents"
        if active_only:
            query += " WHERE status NOT IN ('COMPLETED', 'FAILED', 'CANCELLED')"
        query += " ORDER BY created_at, agent_id"
        with self.connect() as connection:
            return tuple(self._agent(row) for row in connection.execute(query).fetchall())

    def messages_for_agent(self, agent_id: str) -> tuple[dict[str, Any], ...]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM mailbox WHERE target_agent_id = ? ORDER BY created_at, message_id", (agent_id,)
            ).fetchall()
            return tuple(self._message(row).to_dict() for row in rows)

    def has_pending_child_reports(self, agent_id: str) -> bool:
        with self.connect() as connection:
            return bool(
                connection.execute(
                    "SELECT 1 FROM mailbox WHERE target_agent_id = ? AND type IN ('child.completed', 'child.failed') "
                    "AND status = 'PENDING' LIMIT 1",
                    (agent_id,),
                ).fetchone()
            )

    def events_for_task(self, task_id: str) -> tuple[dict[str, Any], ...]:
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

    def counts(self) -> dict[str, int]:
        with self.connect() as connection:
            return {
                "inbox_events": int(connection.execute("SELECT count(*) FROM inbox_events").fetchone()[0]),
                "due_inbox_sessions": int(
                    connection.execute(
                        "SELECT count(DISTINCT session_id) FROM inbox_events "
                        "WHERE status IN ('PENDING', 'DEFERRED') AND available_at <= ?",
                        (utc_now(),),
                    ).fetchone()[0]
                ),
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

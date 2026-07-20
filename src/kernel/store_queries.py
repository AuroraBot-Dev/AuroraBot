"""Read-only Task, Agent, causal event and situation queries."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from src.contracts.agent import AgentInstance, TaskState
from src.kernel.store_base import RuntimeStoreBase, _json, utc_now


class StoreQueriesMixin(RuntimeStoreBase):
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

    def situations(self) -> tuple[dict[str, Any], ...]:
        now = utc_now()
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM situations WHERE status = 'OPEN' AND expires_at > ? ORDER BY priority DESC, created_at",
                (now,),
            ).fetchall()
            return tuple(
                {
                    "situation_id": row["situation_id"],
                    "audience_ref": row["audience_ref"],
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
        audience_ref: str,
    ) -> str:
        now_dt = datetime.now(UTC)
        situation_id = str(uuid4())
        with self.transaction() as connection:
            connection.execute(
                "INSERT INTO situations (situation_id, audience_ref, source, type, summary, payload_json, priority, "
                "status, claimed_by_agent_id, expires_at, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, 'OPEN', NULL, ?, ?, ?)",
                (
                    situation_id,
                    audience_ref,
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
                "pending_effect_activities": int(
                    connection.execute(
                        "SELECT count(*) FROM activities WHERE kind = 'effect' AND status = 'PENDING'"
                    ).fetchone()[0]
                ),
                "processing_effect_activities": int(
                    connection.execute(
                        "SELECT count(*) FROM activities WHERE kind = 'effect' AND status = 'PROCESSING'"
                    ).fetchone()[0]
                ),
                "pending_publication_activities": int(
                    connection.execute(
                        "SELECT count(*) FROM activities WHERE kind = 'publication' AND status = 'PENDING'"
                    ).fetchone()[0]
                ),
                "processing_publication_activities": int(
                    connection.execute(
                        "SELECT count(*) FROM activities WHERE kind = 'publication' AND status = 'PROCESSING'"
                    ).fetchone()[0]
                ),
            }

"""Task ingress, effect receipts and mailbox leasing."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from src.contracts.agent import (
    ActivityStatus,
    AgentInstance,
    AgentMessage,
    AgentStatus,
    TaskBudget,
    TaskState,
    TaskStatus,
)
from src.kernel.store_base import RuntimeStoreBase, _json, utc_now


class StoreIngressMixin(RuntimeStoreBase):
    def create_task(
        self,
        *,
        external_message_id: str,
        session_id: str,
        summary: str,
        payload: dict[str, Any],
        autonomous: bool,
        root_profile: str,
        budget: TaskBudget,
        priority: int,
    ) -> TaskState | None:
        now = utc_now()
        task_id = str(uuid4())
        agent_id = str(uuid4())
        with self.transaction() as connection:
            duplicate = connection.execute(
                "SELECT event_id FROM causal_events WHERE external_message_id = ?",
                (external_message_id,),
            ).fetchone()
            if duplicate is not None:
                return None
            connection.execute(
                "INSERT INTO tasks VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0, ?, ?, ?, ?, ?, NULL)",
                (
                    task_id,
                    agent_id,
                    external_message_id,
                    session_id,
                    summary,
                    int(autonomous),
                    TaskStatus.ACTIVE,
                    budget.max_model_calls,
                    budget.max_tool_calls,
                    budget.max_duration_seconds,
                    now,
                    now,
                ),
            )
            connection.execute(
                "INSERT INTO agents VALUES (?, ?, NULL, ?, 0, ?, ?, 0, '{}', ?, ?, ?)",
                (agent_id, task_id, root_profile, summary, AgentStatus.READY, now, now, summary),
            )
            message_id = self._insert_message(
                connection,
                task_id=task_id,
                target_agent_id=agent_id,
                message_type="task.started",
                payload=payload,
                causation_id=None,
                correlation_id=task_id,
                priority=priority,
                now=now,
            )
            connection.execute(
                "INSERT INTO causal_events VALUES (?, ?, ?, ?, ?, ?, NULL, ?, ?, ?)",
                (
                    str(uuid4()),
                    task_id,
                    agent_id,
                    "task.started",
                    summary,
                    _json(payload),
                    task_id,
                    external_message_id,
                    now,
                ),
            )
        task = self.get_task(task_id)
        assert task is not None and message_id
        return task

    def ingest_activity_receipt(
        self,
        *,
        external_message_id: str,
        request_id: str,
        event_type: str,
        summary: str,
        payload: dict[str, Any],
    ) -> tuple[bool, str | None]:
        """Consume an effect receipt once, deriving authority from the persisted request.

        The boolean distinguishes a known late/duplicate receipt from an unrelated
        external event, so only the latter becomes an ambient situation.
        """
        now = utc_now()
        with self.transaction() as connection:
            if connection.execute(
                "SELECT 1 FROM causal_events WHERE external_message_id = ?", (external_message_id,)
            ).fetchone():
                return True, None
            row = connection.execute(
                "SELECT a.*, t.status AS task_status FROM activities a "
                "JOIN tasks t ON t.task_id = a.task_id "
                "WHERE a.idempotency_key = ? AND a.kind = 'effect'",
                (request_id,),
            ).fetchone()
            if row is None:
                return False, None
            request = json.loads(row["request_json"])
            capability = payload.get("capability")
            if not isinstance(capability, str) or capability != request.get("capability"):
                return False, None
            if row["status"] != ActivityStatus.PROCESSING or row["task_status"] != TaskStatus.ACTIVE:
                connection.execute(
                    "INSERT INTO causal_events VALUES (?, ?, ?, 'effect.receipt_ignored', ?, ?, ?, ?, ?, ?)",
                    (
                        str(uuid4()),
                        row["task_id"],
                        row["agent_id"],
                        f"Ignored late or duplicate receipt for {capability}",
                        _json(payload),
                        row["activity_id"],
                        row["task_id"],
                        external_message_id,
                        now,
                    ),
                )
                return True, None
            status = ActivityStatus.COMPLETED if event_type == "effect.succeeded" else ActivityStatus.ERROR
            connection.execute(
                "UPDATE activities SET status = ?, result_json = ?, error = ?, lease_until = NULL, updated_at = ? "
                "WHERE activity_id = ?",
                (
                    status,
                    _json(payload.get("result")) if event_type == "effect.succeeded" else None,
                    payload.get("error") if event_type == "effect.failed" else None,
                    now,
                    row["activity_id"],
                ),
            )
            terminal = request.get("result_mode") == "terminal"
            message_id: str | None = None
            if not (terminal and event_type == "effect.succeeded"):
                message_payload = {**payload, "activity_id": row["activity_id"], "request": request}
                message_id = self._insert_message(
                    connection,
                    task_id=str(row["task_id"]),
                    target_agent_id=str(row["agent_id"]),
                    message_type=event_type,
                    payload=message_payload,
                    causation_id=str(row["activity_id"]),
                    correlation_id=str(row["task_id"]),
                    priority=int(row["priority"]),
                    now=now,
                )
            if terminal and event_type == "effect.succeeded":
                connection.execute(
                    "UPDATE agents SET status = 'COMPLETED', last_summary = ?, updated_at = ? WHERE agent_id = ?",
                    (summary, now, row["agent_id"]),
                )
                self._end_task(connection, str(row["task_id"]), TaskStatus.COMPLETED, "terminal_effect_succeeded", now)
            connection.execute(
                "INSERT INTO causal_events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    str(uuid4()),
                    row["task_id"],
                    row["agent_id"],
                    event_type,
                    summary,
                    _json(payload),
                    row["activity_id"],
                    row["task_id"],
                    external_message_id,
                    now,
                ),
            )
            return True, message_id

    def claim_message(self, lease_seconds: float) -> tuple[AgentMessage, AgentInstance, TaskState] | None:
        now_dt = datetime.now(UTC)
        now = now_dt.isoformat()
        lease = (now_dt + timedelta(seconds=lease_seconds)).isoformat()
        with self.transaction() as connection:
            connection.execute(
                "UPDATE mailbox SET status = 'PENDING', lease_until = NULL WHERE status = 'PROCESSING' "
                "AND lease_until < ?",
                (now,),
            )
            row = connection.execute(
                "SELECT m.* FROM mailbox m JOIN tasks t ON t.task_id = m.task_id "
                "JOIN agents a ON a.agent_id = m.target_agent_id "
                "WHERE m.status = 'PENDING' AND m.available_at <= ? AND t.status = 'ACTIVE' "
                "AND NOT EXISTS (SELECT 1 FROM mailbox busy WHERE busy.target_agent_id = a.agent_id "
                "AND busy.status = 'PROCESSING') "
                "AND ((a.status = 'READY') "
                "OR (a.status = 'WAITING_MODEL' AND m.type IN ('model.completed', 'model.failed')) "
                "OR (a.status = 'WAITING_EFFECT' AND m.type IN ('effect.succeeded', 'effect.failed')) "
                "OR (a.status = 'WAITING_CHILDREN' AND m.type IN ('child.completed', 'child.failed'))) "
                "ORDER BY m.priority DESC, m.created_at, m.message_id LIMIT 1",
                (now,),
            ).fetchone()
            if row is None:
                return None
            updated = connection.execute(
                "UPDATE mailbox SET status = 'PROCESSING', lease_until = ?, attempts = attempts + 1 "
                "WHERE message_id = ? AND status = 'PENDING'",
                (lease, row["message_id"]),
            )
            if updated.rowcount != 1:
                return None
            # The mailbox lease is the per-Agent execution lock. Keeping the
            # semantic WAITING_* state intact prevents unrelated wake-ups.
            message_row = connection.execute(
                "SELECT * FROM mailbox WHERE message_id = ?", (row["message_id"],)
            ).fetchone()
            agent_row = connection.execute(
                "SELECT * FROM agents WHERE agent_id = ?", (row["target_agent_id"],)
            ).fetchone()
            task_row = connection.execute("SELECT * FROM tasks WHERE task_id = ?", (row["task_id"],)).fetchone()
            assert message_row is not None and agent_row is not None and task_row is not None
            return self._message(message_row), self._agent(agent_row), self._task(task_row)

    def fail_message(self, message_id: str, agent_id: str, error: str) -> None:
        now = utc_now()
        with self.transaction() as connection:
            connection.execute(
                "UPDATE mailbox SET status = 'ERROR', lease_until = NULL, completed_at = ? WHERE message_id = ?",
                (now, message_id),
            )
            connection.execute(
                "UPDATE agents SET status = 'FAILED', last_summary = ?, updated_at = ? WHERE agent_id = ?",
                (error, now, agent_id),
            )

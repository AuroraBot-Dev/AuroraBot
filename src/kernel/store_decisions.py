"""Atomic Agent Decision commits, supervision updates and Task termination."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from src.contracts.agent import (
    AgentInstance,
    AgentMessage,
    AgentStatus,
    ChildResult,
    MessageStatus,
    TaskStatus,
)
from src.kernel.store_base import RuntimeStoreBase, _json, utc_now


class StoreDecisionsMixin(RuntimeStoreBase):
    def apply_decision(
        self,
        *,
        message: AgentMessage,
        agent: AgentInstance,
        action: dict[str, Any],
        state_patch: dict[str, Any],
        limits: dict[str, int],
        priority: int,
    ) -> tuple[str, ...]:
        """Apply one already-authorized decision and all of its outbox writes atomically."""
        now = utc_now()
        created: list[str] = []
        with self.transaction() as connection:
            message_row = connection.execute(
                "SELECT * FROM mailbox WHERE message_id = ?", (message.message_id,)
            ).fetchone()
            agent_row = connection.execute("SELECT * FROM agents WHERE agent_id = ?", (agent.agent_id,)).fetchone()
            task_row = connection.execute("SELECT * FROM tasks WHERE task_id = ?", (agent.task_id,)).fetchone()
            if message_row is None or message_row["status"] != MessageStatus.PROCESSING:
                raise RuntimeError("Agent message lease was lost")
            if agent_row is None or int(agent_row["revision"]) != agent.revision:
                raise RuntimeError("Agent revision conflict")
            if task_row is None or task_row["status"] != TaskStatus.ACTIVE:
                raise RuntimeError("Task is no longer active")
            state = json.loads(agent_row["state_json"])
            state.update(state_patch)
            status = AgentStatus.READY
            summary = str(action.get("summary", message.type))
            kind = action["kind"]
            if kind == "model":
                if int(task_row["model_calls"]) >= int(task_row["max_model_calls"]):
                    self._end_task(
                        connection, agent.task_id, TaskStatus.BUDGET_EXHAUSTED, "model_budget_exhausted", now
                    )
                    status = AgentStatus.CANCELLED
                else:
                    activity_id = str(uuid4())
                    connection.execute(
                        "INSERT INTO activities VALUES (?, ?, ?, 'model', ?, 'PENDING', ?, ?, NULL, ?, ?, NULL, NULL)",
                        (
                            activity_id,
                            agent.task_id,
                            agent.agent_id,
                            _json(action["request"]),
                            priority,
                            activity_id,
                            now,
                            now,
                        ),
                    )
                    connection.execute(
                        "UPDATE tasks SET model_calls = model_calls + 1, updated_at = ? WHERE task_id = ?",
                        (now, agent.task_id),
                    )
                    status = AgentStatus.WAITING_MODEL
                    created.append(activity_id)
            elif kind in {"effect", "publication"}:
                if int(task_row["tool_calls"]) >= int(task_row["max_tool_calls"]):
                    self._end_task(connection, agent.task_id, TaskStatus.BUDGET_EXHAUSTED, "tool_budget_exhausted", now)
                    status = AgentStatus.CANCELLED
                else:
                    activity_id = str(uuid4())
                    request_id = str(uuid4())
                    request = {**action["request"], "request_id": request_id}
                    connection.execute(
                        "INSERT INTO activities VALUES (?, ?, ?, ?, ?, 'PENDING', ?, ?, NULL, ?, ?, NULL, NULL)",
                        (
                            activity_id,
                            agent.task_id,
                            agent.agent_id,
                            kind,
                            _json(request),
                            priority,
                            request_id,
                            now,
                            now,
                        ),
                    )
                    connection.execute(
                        "UPDATE tasks SET tool_calls = tool_calls + 1, updated_at = ? WHERE task_id = ?",
                        (now, agent.task_id),
                    )
                    status = AgentStatus.WAITING_EFFECT
                    created.append(activity_id)
            elif kind == "delegate":
                requests = action["requests"]
                current_count = int(
                    connection.execute("SELECT count(*) FROM agents WHERE task_id = ?", (agent.task_id,)).fetchone()[0]
                )
                active_count = int(
                    connection.execute(
                        "SELECT count(*) FROM agents WHERE status NOT IN ('COMPLETED', 'FAILED', 'CANCELLED')"
                    ).fetchone()[0]
                )
                child_count = int(
                    connection.execute(
                        "SELECT count(*) FROM agents WHERE parent_agent_id = ?", (agent.agent_id,)
                    ).fetchone()[0]
                )
                if (
                    agent.depth >= limits["max_depth"]
                    or child_count + len(requests) > limits["max_children_per_agent"]
                    or current_count + len(requests) > limits["max_agents_per_task"]
                    or active_count + len(requests) > limits["max_active_agents"]
                ):
                    raise PermissionError("Agent delegation limit exceeded")
                for request in requests:
                    child_id = str(uuid4())
                    instruction = str(request["instruction"])
                    connection.execute(
                        "INSERT INTO agents VALUES (?, ?, ?, ?, ?, ?, 'READY', 0, '{}', ?, ?, ?)",
                        (
                            child_id,
                            agent.task_id,
                            agent.agent_id,
                            request["profile_id"],
                            agent.depth + 1,
                            instruction,
                            now,
                            now,
                            instruction,
                        ),
                    )
                    child_message = self._insert_message(
                        connection,
                        task_id=agent.task_id,
                        target_agent_id=child_id,
                        message_type="agent.assigned",
                        payload={"instruction": instruction, "parent_agent_id": agent.agent_id},
                        causation_id=message.message_id,
                        correlation_id=agent.task_id,
                        priority=priority,
                        now=now,
                    )
                    created.extend((child_id, child_message))
                status = AgentStatus.WAITING_CHILDREN
            elif kind == "wait":
                status = AgentStatus.WAITING_CHILDREN
            elif kind in {"complete", "fail"}:
                status = AgentStatus.COMPLETED if kind == "complete" else AgentStatus.FAILED
                if agent.parent_agent_id is not None:
                    result = ChildResult(
                        child_agent_id=agent.agent_id,
                        status="completed" if kind == "complete" else "failed",
                        summary=summary,
                        artifacts=tuple(action.get("artifacts", [])),
                        error=action.get("error"),
                    )
                    child_message = self._insert_message(
                        connection,
                        task_id=agent.task_id,
                        target_agent_id=agent.parent_agent_id,
                        message_type="child.completed" if kind == "complete" else "child.failed",
                        payload=result.to_dict(),
                        causation_id=message.message_id,
                        correlation_id=agent.task_id,
                        priority=priority,
                        now=now,
                    )
                    created.append(child_message)
                else:
                    task_status = (
                        TaskStatus.SILENT
                        if action.get("silent")
                        else (TaskStatus.ERROR if kind == "fail" else TaskStatus.COMPLETED)
                    )
                    self._end_task(connection, agent.task_id, task_status, summary, now)
            else:
                raise ValueError(f"unknown Agent action {kind}")
            for situation_id in action.get("claims", []):
                claimed = connection.execute(
                    "UPDATE situations SET status = 'CLAIMED', claimed_by_agent_id = ?, updated_at = ? "
                    "WHERE situation_id = ? AND status = 'OPEN' AND expires_at > ?",
                    (agent.agent_id, now, situation_id, now),
                )
                if claimed.rowcount != 1:
                    raise PermissionError(f"situation is unavailable: {situation_id}")
            connection.execute(
                "UPDATE agents SET status = ?, revision = revision + 1, state_json = ?, "
                "last_summary = ?, updated_at = ? "
                "WHERE agent_id = ?",
                (status, _json(state), summary, now, agent.agent_id),
            )
            connection.execute(
                "UPDATE mailbox SET status = 'COMPLETED', lease_until = NULL, completed_at = ? WHERE message_id = ?",
                (now, message.message_id),
            )
            connection.execute(
                "INSERT INTO causal_events VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)",
                (
                    str(uuid4()),
                    agent.task_id,
                    agent.agent_id,
                    f"agent.{kind}",
                    summary,
                    _json(action),
                    message.message_id,
                    agent.task_id,
                    now,
                ),
            )
        return tuple(created)

    @staticmethod
    def _end_task(connection: sqlite3.Connection, task_id: str, status: TaskStatus, reason: str, now: str) -> None:
        connection.execute(
            "UPDATE tasks SET status = ?, termination_reason = ?, updated_at = ? WHERE task_id = ?",
            (status, reason, now, task_id),
        )
        connection.execute(
            "UPDATE agents SET status = 'CANCELLED', updated_at = ? WHERE task_id = ? "
            "AND status NOT IN ('COMPLETED', 'FAILED', 'CANCELLED')",
            (now, task_id),
        )
        connection.execute(
            "UPDATE mailbox SET status = 'ERROR', completed_at = ?, lease_until = NULL WHERE task_id = ? "
            "AND status IN ('PENDING', 'PROCESSING')",
            (now, task_id),
        )
        connection.execute(
            "UPDATE activities SET status = 'CANCELLED', updated_at = ?, lease_until = NULL WHERE task_id = ? "
            "AND status IN ('PENDING', 'PROCESSING')",
            (now, task_id),
        )
        connection.execute(
            "UPDATE reply_grants SET status = 'REVOKED' WHERE task_id = ? AND status = 'ACTIVE'",
            (task_id,),
        )

    def cancel_task(self, task_id: str, reason: str) -> None:
        with self.transaction() as connection:
            self._end_task(connection, task_id, TaskStatus.CANCELLED, reason, utc_now())

    def expire_tasks(self) -> tuple[str, ...]:
        now_dt = datetime.now(UTC)
        expired: list[str] = []
        with self.transaction() as connection:
            rows = connection.execute("SELECT * FROM tasks WHERE status = 'ACTIVE'").fetchall()
            for row in rows:
                if (now_dt - datetime.fromisoformat(row["started_at"])).total_seconds() <= row["max_duration_seconds"]:
                    continue
                self._end_task(
                    connection,
                    str(row["task_id"]),
                    TaskStatus.BUDGET_EXHAUSTED,
                    "duration_budget_exhausted",
                    now_dt.isoformat(),
                )
                expired.append(str(row["task_id"]))
        return tuple(expired)

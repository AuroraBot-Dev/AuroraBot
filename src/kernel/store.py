"""Transactional SQLite store for Tasks, Agents, mailboxes, Activities and causal facts."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from src.kernel.contracts import (
    ActivityRequest,
    ActivityStatus,
    AgentInstance,
    AgentMessage,
    AgentStatus,
    ChildResult,
    MessageStatus,
    TaskBudget,
    TaskState,
    TaskStatus,
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_meta (
    version INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS tasks (
    task_id TEXT PRIMARY KEY,
    root_agent_id TEXT NOT NULL,
    root_message_id TEXT NOT NULL UNIQUE,
    session_id TEXT NOT NULL,
    root_summary TEXT NOT NULL,
    autonomous INTEGER NOT NULL CHECK (autonomous IN (0, 1)),
    status TEXT NOT NULL,
    model_calls INTEGER NOT NULL,
    tool_calls INTEGER NOT NULL,
    max_model_calls INTEGER NOT NULL,
    max_tool_calls INTEGER NOT NULL,
    max_duration_seconds REAL NOT NULL,
    started_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    termination_reason TEXT
);
CREATE TABLE IF NOT EXISTS agents (
    agent_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES tasks(task_id),
    parent_agent_id TEXT REFERENCES agents(agent_id),
    profile_id TEXT NOT NULL,
    depth INTEGER NOT NULL,
    assignment TEXT NOT NULL,
    status TEXT NOT NULL,
    revision INTEGER NOT NULL,
    state_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_summary TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_agents_task ON agents(task_id, status);
CREATE INDEX IF NOT EXISTS idx_agents_parent ON agents(parent_agent_id, status);
CREATE TABLE IF NOT EXISTS mailbox (
    message_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES tasks(task_id),
    target_agent_id TEXT NOT NULL REFERENCES agents(agent_id),
    type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    causation_id TEXT,
    correlation_id TEXT NOT NULL,
    priority INTEGER NOT NULL,
    status TEXT NOT NULL,
    available_at TEXT NOT NULL,
    lease_until TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    completed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_mailbox_ready ON mailbox(status, priority DESC, available_at, created_at);
CREATE INDEX IF NOT EXISTS idx_mailbox_agent ON mailbox(target_agent_id, status, created_at);
CREATE TABLE IF NOT EXISTS activities (
    activity_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES tasks(task_id),
    agent_id TEXT NOT NULL REFERENCES agents(agent_id),
    kind TEXT NOT NULL CHECK (kind IN ('model', 'effect')),
    request_json TEXT NOT NULL,
    status TEXT NOT NULL,
    priority INTEGER NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    lease_until TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    result_json TEXT,
    error TEXT
);
CREATE INDEX IF NOT EXISTS idx_activities_ready ON activities(kind, status, priority DESC, created_at);
CREATE TABLE IF NOT EXISTS causal_events (
    event_id TEXT PRIMARY KEY,
    task_id TEXT,
    agent_id TEXT,
    type TEXT NOT NULL,
    summary TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    causation_id TEXT,
    correlation_id TEXT NOT NULL,
    external_message_id TEXT UNIQUE,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_causal_task ON causal_events(task_id, created_at);
CREATE TABLE IF NOT EXISTS situations (
    situation_id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    type TEXT NOT NULL,
    summary TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    priority INTEGER NOT NULL,
    status TEXT NOT NULL,
    claimed_by_agent_id TEXT,
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_situations_open ON situations(status, expires_at, priority DESC);
"""


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


class SQLiteRuntimeStore:
    """Small transactional store; callers keep model and Platform I/O outside its transactions."""

    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        return connection

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
            except Exception:
                connection.rollback()
                raise
            connection.commit()

    def initialize(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(_SCHEMA)
            row = connection.execute("SELECT version FROM schema_meta LIMIT 1").fetchone()
            if row is None:
                connection.execute("INSERT INTO schema_meta(version) VALUES (1)")
            elif int(row["version"]) != 1:
                raise RuntimeError("unsupported Agent runtime database schema")
            connection.commit()
        self.recover_interrupted()

    def recover_interrupted(self) -> None:
        now = utc_now()
        with self.transaction() as connection:
            connection.execute("UPDATE mailbox SET status = 'PENDING', lease_until = NULL WHERE status = 'PROCESSING'")
            running = connection.execute("SELECT agent_id FROM agents WHERE status = 'RUNNING'").fetchall()
            for row in running:
                connection.execute(
                    "UPDATE agents SET status = 'READY', updated_at = ? WHERE agent_id = ?",
                    (now, row["agent_id"]),
                )
            interrupted = connection.execute("SELECT * FROM activities WHERE status = 'PROCESSING'").fetchall()
            for row in interrupted:
                connection.execute(
                    "UPDATE activities SET status = 'ERROR', lease_until = NULL, error = ?, updated_at = ? "
                    "WHERE activity_id = ?",
                    ("interrupted_by_restart", now, row["activity_id"]),
                )
                self._insert_message(
                    connection,
                    task_id=str(row["task_id"]),
                    target_agent_id=str(row["agent_id"]),
                    message_type=f"{row['kind']}.failed",
                    payload={
                        "activity_id": row["activity_id"],
                        "error": "interrupted_by_restart",
                        "request": json.loads(row["request_json"]),
                    },
                    causation_id=str(row["activity_id"]),
                    correlation_id=str(row["task_id"]),
                    priority=int(row["priority"]),
                    now=now,
                )
                connection.execute(
                    "UPDATE agents SET status = 'READY', updated_at = ? WHERE agent_id = ? AND status NOT IN "
                    "('COMPLETED', 'FAILED', 'CANCELLED')",
                    (now, row["agent_id"]),
                )

    @staticmethod
    def _task(row: sqlite3.Row) -> TaskState:
        return TaskState(
            task_id=str(row["task_id"]),
            root_agent_id=str(row["root_agent_id"]),
            root_message_id=str(row["root_message_id"]),
            session_id=str(row["session_id"]),
            root_summary=str(row["root_summary"]),
            autonomous=bool(row["autonomous"]),
            status=TaskStatus(row["status"]),
            model_calls=int(row["model_calls"]),
            tool_calls=int(row["tool_calls"]),
            max_model_calls=int(row["max_model_calls"]),
            max_tool_calls=int(row["max_tool_calls"]),
            max_duration_seconds=float(row["max_duration_seconds"]),
            started_at=str(row["started_at"]),
            updated_at=str(row["updated_at"]),
            termination_reason=row["termination_reason"],
        )

    @staticmethod
    def _agent(row: sqlite3.Row) -> AgentInstance:
        return AgentInstance(
            agent_id=str(row["agent_id"]),
            task_id=str(row["task_id"]),
            parent_agent_id=row["parent_agent_id"],
            profile_id=str(row["profile_id"]),
            depth=int(row["depth"]),
            assignment=str(row["assignment"]),
            status=AgentStatus(row["status"]),
            revision=int(row["revision"]),
            state=json.loads(row["state_json"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
            last_summary=str(row["last_summary"]),
        )

    @staticmethod
    def _message(row: sqlite3.Row) -> AgentMessage:
        return AgentMessage(
            message_id=str(row["message_id"]),
            task_id=str(row["task_id"]),
            target_agent_id=str(row["target_agent_id"]),
            type=str(row["type"]),
            payload=json.loads(row["payload_json"]),
            causation_id=row["causation_id"],
            correlation_id=str(row["correlation_id"]),
            priority=int(row["priority"]),
            status=MessageStatus(row["status"]),
            available_at=str(row["available_at"]),
            lease_until=row["lease_until"],
            created_at=str(row["created_at"]),
        )

    @staticmethod
    def _activity(row: sqlite3.Row) -> ActivityRequest:
        return ActivityRequest(
            activity_id=str(row["activity_id"]),
            task_id=str(row["task_id"]),
            agent_id=str(row["agent_id"]),
            kind=row["kind"],
            request=json.loads(row["request_json"]),
            status=ActivityStatus(row["status"]),
            priority=int(row["priority"]),
            idempotency_key=str(row["idempotency_key"]),
            lease_until=row["lease_until"],
            created_at=str(row["created_at"]),
        )

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
        terminal: bool = False,
    ) -> str | None:
        now = utc_now()
        with self.transaction() as connection:
            if connection.execute(
                "SELECT 1 FROM causal_events WHERE external_message_id = ?", (external_message_id,)
            ).fetchone():
                return None
            row = connection.execute(
                "SELECT * FROM activities WHERE idempotency_key = ? AND kind = 'effect'",
                (request_id,),
            ).fetchone()
            if row is None:
                return None
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
            message_payload = {**payload, "activity_id": row["activity_id"], "request": json.loads(row["request_json"])}
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
            connection.execute(
                "UPDATE agents SET status = 'READY', updated_at = ? WHERE agent_id = ? AND status NOT IN "
                "('COMPLETED', 'FAILED', 'CANCELLED')",
                (now, row["agent_id"]),
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
            return message_id

    @staticmethod
    def _insert_message(
        connection: sqlite3.Connection,
        *,
        task_id: str,
        target_agent_id: str,
        message_type: str,
        payload: dict[str, Any],
        causation_id: str | None,
        correlation_id: str,
        priority: int,
        now: str,
    ) -> str:
        message_id = str(uuid4())
        connection.execute(
            "INSERT INTO mailbox VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, 0, ?, NULL)",
            (
                message_id,
                task_id,
                target_agent_id,
                message_type,
                _json(payload),
                causation_id,
                correlation_id,
                priority,
                MessageStatus.PENDING,
                now,
                now,
            ),
        )
        return message_id

    def claim_message(self, lease_seconds: float) -> tuple[AgentMessage, AgentInstance, TaskState] | None:
        now_dt = datetime.now(UTC)
        now = now_dt.isoformat()
        lease = (now_dt + timedelta(seconds=lease_seconds)).isoformat()
        with self.transaction() as connection:
            connection.execute(
                "UPDATE agents SET status = 'READY', updated_at = ? WHERE status = 'RUNNING' AND agent_id IN "
                "(SELECT target_agent_id FROM mailbox WHERE status = 'PROCESSING' AND lease_until < ?)",
                (now, now),
            )
            connection.execute(
                "UPDATE mailbox SET status = 'PENDING', lease_until = NULL WHERE status = 'PROCESSING' "
                "AND lease_until < ?",
                (now,),
            )
            row = connection.execute(
                "SELECT m.* FROM mailbox m JOIN tasks t ON t.task_id = m.task_id "
                "JOIN agents a ON a.agent_id = m.target_agent_id "
                "WHERE m.status = 'PENDING' AND m.available_at <= ? AND t.status = 'ACTIVE' "
                "AND a.status NOT IN ('RUNNING', 'COMPLETED', 'FAILED', 'CANCELLED') "
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
            connection.execute(
                "UPDATE agents SET status = 'RUNNING', updated_at = ? WHERE agent_id = ?",
                (now, row["target_agent_id"]),
            )
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
        self, source: str, event_type: str, summary: str, payload: dict[str, Any], priority: int, ttl_seconds: float
    ) -> str:
        now_dt = datetime.now(UTC)
        situation_id = str(uuid4())
        with self.transaction() as connection:
            connection.execute(
                "INSERT INTO situations VALUES (?, ?, ?, ?, ?, ?, 'OPEN', NULL, ?, ?, ?)",
                (
                    situation_id,
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
            }

    def claim_activities(self, kind: str, limit: int, lease_seconds: float) -> tuple[ActivityRequest, ...]:
        now_dt = datetime.now(UTC)
        now = now_dt.isoformat()
        lease = (now_dt + timedelta(seconds=lease_seconds)).isoformat()
        with self.transaction() as connection:
            rows = connection.execute(
                "SELECT a.* FROM activities a JOIN tasks t ON t.task_id = a.task_id "
                "WHERE a.kind = ? AND a.status = 'PENDING' AND t.status = 'ACTIVE' "
                "ORDER BY a.priority DESC, a.created_at LIMIT ?",
                (kind, limit),
            ).fetchall()
            result: list[ActivityRequest] = []
            for row in rows:
                connection.execute(
                    "UPDATE activities SET status = 'PROCESSING', lease_until = ?, updated_at = ? "
                    "WHERE activity_id = ?",
                    (lease, now, row["activity_id"]),
                )
                updated = connection.execute(
                    "SELECT * FROM activities WHERE activity_id = ?", (row["activity_id"],)
                ).fetchone()
                assert updated is not None
                result.append(self._activity(updated))
            return tuple(result)

    def claim_effect_activities(
        self, capabilities: frozenset[str], limit: int, lease_seconds: float
    ) -> tuple[ActivityRequest, ...]:
        now_dt = datetime.now(UTC)
        now = now_dt.isoformat()
        lease = (now_dt + timedelta(seconds=lease_seconds)).isoformat()
        with self.transaction() as connection:
            processing = int(
                connection.execute(
                    "SELECT count(*) FROM activities WHERE kind = 'effect' AND status = 'PROCESSING'"
                ).fetchone()[0]
            )
            available = max(0, limit - processing)
            if available == 0:
                return ()
            rows = connection.execute(
                "SELECT a.* FROM activities a JOIN tasks t ON t.task_id = a.task_id "
                "WHERE a.kind = 'effect' AND a.status = 'PENDING' AND t.status = 'ACTIVE' "
                "ORDER BY a.priority DESC, a.created_at"
            ).fetchall()
            result: list[ActivityRequest] = []
            for row in rows:
                request = json.loads(row["request_json"])
                if request.get("capability") not in capabilities:
                    continue
                connection.execute(
                    "UPDATE activities SET status = 'PROCESSING', lease_until = ?, updated_at = ? "
                    "WHERE activity_id = ?",
                    (lease, now, row["activity_id"]),
                )
                updated = connection.execute(
                    "SELECT * FROM activities WHERE activity_id = ?", (row["activity_id"],)
                ).fetchone()
                assert updated is not None
                result.append(self._activity(updated))
                if len(result) >= available:
                    break
            return tuple(result)

    def complete_model_activity(self, activity_id: str, result: dict[str, Any] | None, error: str | None) -> None:
        now = utc_now()
        with self.transaction() as connection:
            row = connection.execute("SELECT * FROM activities WHERE activity_id = ?", (activity_id,)).fetchone()
            if row is None or row["status"] not in {ActivityStatus.PROCESSING, ActivityStatus.PENDING}:
                return
            status = ActivityStatus.ERROR if error else ActivityStatus.COMPLETED
            connection.execute(
                "UPDATE activities SET status = ?, result_json = ?, error = ?, lease_until = NULL, updated_at = ? "
                "WHERE activity_id = ?",
                (status, _json(result) if result is not None else None, error, now, activity_id),
            )
            message_type = "model.failed" if error else "model.completed"
            payload = (
                {"activity_id": activity_id, "error": error}
                if error
                else {"activity_id": activity_id, **(result or {})}
            )
            self._insert_message(
                connection,
                task_id=str(row["task_id"]),
                target_agent_id=str(row["agent_id"]),
                message_type=message_type,
                payload=payload,
                causation_id=activity_id,
                correlation_id=str(row["task_id"]),
                priority=int(row["priority"]),
                now=now,
            )
            connection.execute(
                "UPDATE agents SET status = 'READY', updated_at = ? WHERE agent_id = ? AND status NOT IN "
                "('COMPLETED', 'FAILED', 'CANCELLED')",
                (now, row["agent_id"]),
            )
            connection.execute(
                "INSERT INTO causal_events VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)",
                (
                    str(uuid4()),
                    row["task_id"],
                    row["agent_id"],
                    message_type,
                    message_type,
                    _json(payload),
                    activity_id,
                    row["task_id"],
                    now,
                ),
            )

    def mark_effect_dispatched(self, activity_id: str, error: str | None = None) -> None:
        if error is None:
            return
        now = utc_now()
        with self.transaction() as connection:
            connection.execute(
                "UPDATE activities SET status = 'ERROR', error = ?, lease_until = NULL, updated_at = ? "
                "WHERE activity_id = ?",
                (error, now, activity_id),
            )

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
            elif kind == "effect":
                if int(task_row["tool_calls"]) >= int(task_row["max_tool_calls"]):
                    self._end_task(connection, agent.task_id, TaskStatus.BUDGET_EXHAUSTED, "tool_budget_exhausted", now)
                    status = AgentStatus.CANCELLED
                else:
                    activity_id = str(uuid4())
                    request_id = str(uuid4())
                    request = {**action["request"], "request_id": request_id}
                    connection.execute(
                        "INSERT INTO activities VALUES (?, ?, ?, 'effect', ?, 'PENDING', ?, ?, NULL, ?, ?, NULL, NULL)",
                        (activity_id, agent.task_id, agent.agent_id, _json(request), priority, request_id, now, now),
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
                    connection.execute(
                        "UPDATE agents SET status = 'READY', updated_at = ? WHERE agent_id = ? AND status NOT IN "
                        "('COMPLETED', 'FAILED', 'CANCELLED')",
                        (now, agent.parent_agent_id),
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

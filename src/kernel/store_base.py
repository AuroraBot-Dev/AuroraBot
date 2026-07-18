"""Connections, migrations and row conversion shared by Store repositories."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from src.contracts.agent import (
    ActivityRequest,
    ActivityStatus,
    AgentInstance,
    AgentMessage,
    AgentStatus,
    MessageStatus,
    TaskState,
    TaskStatus,
)
from src.kernel.store_schema import _ACTIVE_ACTIVITY_INDEX, _SCHEMA, _SCHEMA_VERSION


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


class RuntimeStoreBase:
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
                connection.execute("INSERT INTO schema_meta(version) VALUES (?)", (_SCHEMA_VERSION,))
            elif int(row["version"]) not in {1, _SCHEMA_VERSION}:
                raise RuntimeError("unsupported Agent runtime database schema")
            # Version 2 makes the single-active-turn rule durable instead of relying
            # only on scheduler timing. Existing v1 stores can migrate in place.
            connection.execute(_ACTIVE_ACTIVITY_INDEX)
            connection.execute("UPDATE schema_meta SET version = ?", (_SCHEMA_VERSION,))
            connection.commit()
        self.recover_interrupted()

    def recover_interrupted(self) -> None:
        now = utc_now()
        with self.transaction() as connection:
            connection.execute("UPDATE mailbox SET status = 'PENDING', lease_until = NULL WHERE status = 'PROCESSING'")
            # RUNNING only exists in pre-v2 stores; the mailbox lease is the lock now.
            connection.execute(
                "UPDATE agents SET status = 'READY', updated_at = ? WHERE status = 'RUNNING'",
                (now,),
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

    @staticmethod
    def _end_task(connection: sqlite3.Connection, task_id: str, status: TaskStatus, reason: str, now: str) -> None:
        raise NotImplementedError

    def get_task(self, task_id: str) -> TaskState | None:
        raise NotImplementedError

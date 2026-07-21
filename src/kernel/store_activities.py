"""Model and Tool Activity outbox operations."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from src.contracts.agent import ActivityRequest, ActivityStatus
from src.kernel.store_base import RuntimeStoreBase, _json, utc_now


class StoreActivitiesMixin(RuntimeStoreBase):
    def has_claimable_external_activity(self, limit: int) -> bool:
        with self.connect() as connection:
            processing = int(
                connection.execute(
                    "SELECT count(*) FROM activities WHERE kind = 'tool' AND status = 'PROCESSING'"
                ).fetchone()[0]
            )
            if processing >= limit:
                return False
            return bool(
                connection.execute(
                    "SELECT 1 FROM activities a JOIN tasks t ON t.task_id = a.task_id "
                    "WHERE a.kind = 'tool' AND a.status = 'PENDING' "
                    "AND t.status = 'ACTIVE' LIMIT 1"
                ).fetchone()
            )

    def has_recoverable_tool(self) -> bool:
        now = utc_now()
        with self.connect() as connection:
            return bool(
                connection.execute(
                    "SELECT 1 FROM activities a JOIN tasks t ON t.task_id = a.task_id "
                    "WHERE a.kind = 'tool' AND a.status = 'PROCESSING' "
                    "AND (a.lease_until IS NULL OR a.lease_until <= ?) AND t.status = 'ACTIVE' LIMIT 1",
                    (now,),
                ).fetchone()
            )

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

    def claim_tool_activities(self, limit: int, lease_seconds: float) -> tuple[ActivityRequest, ...]:
        now_dt = datetime.now(UTC)
        now = now_dt.isoformat()
        lease = (now_dt + timedelta(seconds=lease_seconds)).isoformat()
        with self.transaction() as connection:
            processing = int(
                connection.execute(
                    "SELECT count(*) FROM activities WHERE kind = 'tool' AND status = 'PROCESSING'"
                ).fetchone()[0]
            )
            available = max(0, limit - processing)
            if available == 0:
                return ()
            rows = connection.execute(
                "SELECT a.* FROM activities a JOIN tasks t ON t.task_id = a.task_id "
                "WHERE a.kind = 'tool' AND a.status = 'PENDING' AND t.status = 'ACTIVE' "
                "ORDER BY a.priority DESC, a.created_at"
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
                if len(result) >= available:
                    break
            return tuple(result)

    def tool_recovery_activities(self) -> tuple[ActivityRequest, ...]:
        now = utc_now()
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT a.* FROM activities a JOIN tasks t ON t.task_id = a.task_id "
                "WHERE a.kind = 'tool' AND a.status = 'PROCESSING' "
                "AND (a.lease_until IS NULL OR a.lease_until <= ?) "
                "AND t.status = 'ACTIVE' ORDER BY a.priority DESC, a.created_at",
                (now,),
            ).fetchall()
            return tuple(self._activity(row) for row in rows)

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

"""Publication grants, recovery queries and three-state receipt commits."""

from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

from src.contracts.agent import ActivityStatus, TaskStatus
from src.kernel.store_base import RuntimeStoreBase, _json, utc_now


class StorePublicationsMixin(RuntimeStoreBase):
    def active_reply_grants(self, task_id: str) -> tuple[dict[str, str], ...]:
        now = utc_now()
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM reply_grants WHERE task_id = ? AND status = 'ACTIVE' AND expires_at > ? "
                "ORDER BY capability_id, route_ref",
                (task_id, now),
            ).fetchall()
            return tuple({str(key): str(value) for key, value in dict(row).items()} for row in rows)

    def reply_grant(self, task_id: str, route_ref: str) -> dict[str, str] | None:
        now = utc_now()
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM reply_grants WHERE task_id = ? AND route_ref = ? AND status = 'ACTIVE' "
                "AND expires_at > ?",
                (task_id, route_ref, now),
            ).fetchone()
            return {str(key): str(value) for key, value in dict(row).items()} if row is not None else None

    def root_amp(self, task_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT payload_json FROM causal_events WHERE task_id = ? AND type = 'task.started' "
                "ORDER BY created_at LIMIT 1",
                (task_id,),
            ).fetchone()
            if row is None:
                return None
            payload = json.loads(row["payload_json"])
            amp = payload.get("amp")
            return amp if isinstance(amp, dict) else None

    def ingest_publication_receipt(
        self,
        *,
        external_message_id: str,
        request_id: str,
        event_type: str,
        summary: str,
        payload: dict[str, Any],
    ) -> tuple[bool, str | None]:
        if event_type not in {
            "publication.succeeded",
            "publication.failed",
            "publication.delivery_unknown",
        }:
            raise ValueError(f"unsupported publication receipt {event_type}")
        now = utc_now()
        with self.transaction() as connection:
            if connection.execute(
                "SELECT 1 FROM causal_events WHERE external_message_id = ?", (external_message_id,)
            ).fetchone():
                return True, None
            row = connection.execute(
                "SELECT a.*, t.status AS task_status FROM activities a "
                "JOIN tasks t ON t.task_id = a.task_id "
                "WHERE a.idempotency_key = ? AND a.kind = 'publication'",
                (request_id,),
            ).fetchone()
            if row is None:
                return False, None
            request = json.loads(row["request_json"])
            for key in ("capability", "endpoint_id", "operation"):
                supplied = payload.get(key)
                if supplied is not None and supplied != request.get(key):
                    return False, None
            if row["status"] != ActivityStatus.PROCESSING or row["task_status"] != TaskStatus.ACTIVE:
                self._record_publication_event(
                    connection,
                    row,
                    "publication.receipt_ignored",
                    f"Ignored late or duplicate receipt for {request_id}",
                    payload,
                    external_message_id,
                    now,
                )
                return True, None
            succeeded = event_type == "publication.succeeded"
            connection.execute(
                "UPDATE activities SET status = ?, result_json = ?, error = ?, lease_until = NULL, updated_at = ? "
                "WHERE activity_id = ?",
                (
                    ActivityStatus.COMPLETED if succeeded else ActivityStatus.ERROR,
                    _json(payload.get("result")) if succeeded else None,
                    payload.get("error") or ("delivery_unknown" if event_type.endswith("delivery_unknown") else None),
                    now,
                    row["activity_id"],
                ),
            )
            complete = succeeded and request.get("completion_mode") == "complete_on_success"
            message_id = None
            if complete:
                connection.execute(
                    "UPDATE agents SET status = 'COMPLETED', last_summary = ?, updated_at = ? WHERE agent_id = ?",
                    (summary, now, row["agent_id"]),
                )
                self._end_task(
                    connection,
                    str(row["task_id"]),
                    TaskStatus.COMPLETED,
                    "publication_succeeded",
                    now,
                )
            else:
                message_id = self._insert_message(
                    connection,
                    task_id=str(row["task_id"]),
                    target_agent_id=str(row["agent_id"]),
                    message_type=event_type,
                    payload={**payload, "activity_id": row["activity_id"], "request": request},
                    causation_id=str(row["activity_id"]),
                    correlation_id=str(row["task_id"]),
                    priority=int(row["priority"]),
                    now=now,
                )
            self._record_publication_event(connection, row, event_type, summary, payload, external_message_id, now)
            return True, message_id

    @staticmethod
    def _record_publication_event(
        connection: Any,
        row: Any,
        event_type: str,
        summary: str,
        payload: dict[str, Any],
        external_message_id: str,
        now: str,
    ) -> None:
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

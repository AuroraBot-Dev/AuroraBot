"""模型调用与外部工具请求的排队和执行。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

from src.contracts.agent import ActivityRequest, ActivityStatus

from .base import RuntimeStoreBase, _json, utc_now
from .status import ACT_PENDING, ACT_PROCESSING, TASK_ACTIVE


class _Msg(StrEnum):
    """本文件内所有用户可见或日志输出的字符串常量。"""

    ACTIVITY_ROW_MISSING = "activity row missing for {activity_id}"


class StoreActivitiesMixin(RuntimeStoreBase):
    """模型调用与外部工具请求的排队和执行。"""

    def has_claimable_external_activity(self, limit: int) -> bool:
        with self.connect() as connection:
            processing = int(
                connection.execute(
                    f"SELECT count(*) FROM activities WHERE kind = 'tool' AND status = {ACT_PROCESSING}"
                ).fetchone()[0]
            )
            if processing >= limit:
                return False
            return bool(
                connection.execute(
                    "SELECT 1 FROM activities a JOIN tasks t ON t.task_id = a.task_id "
                    f"WHERE a.kind = 'tool' AND a.status = {ACT_PENDING} "
                    f"AND t.status = {TASK_ACTIVE} LIMIT 1"
                ).fetchone()
            )

    def has_recoverable_tool(self) -> bool:
        now = utc_now()
        with self.connect() as connection:
            return bool(
                connection.execute(
                    "SELECT 1 FROM activities a JOIN tasks t ON t.task_id = a.task_id "
                    f"WHERE a.kind = 'tool' AND a.status = {ACT_PROCESSING} "
                    f"AND (a.lease_until IS NULL OR a.lease_until <= ?) AND t.status = {TASK_ACTIVE} LIMIT 1",
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
                f"WHERE a.kind = ? AND a.status = {ACT_PENDING} AND t.status = {TASK_ACTIVE} "
                "ORDER BY a.priority DESC, a.created_at LIMIT ?",
                (kind, limit),
            ).fetchall()
            result: list[ActivityRequest] = []
            for row in rows:
                connection.execute(
                    f"UPDATE activities SET status = {ACT_PROCESSING}, lease_until = ?, updated_at = ? "
                    "WHERE activity_id = ?",
                    (lease, now, row["activity_id"]),
                )
                updated = connection.execute(
                    "SELECT * FROM activities WHERE activity_id = ?", (row["activity_id"],)
                ).fetchone()
                if updated is None:
                    raise RuntimeError(_Msg.ACTIVITY_ROW_MISSING.format(activity_id=row["activity_id"]))
                result.append(self._activity(updated))
            return tuple(result)

    def claim_tool_activities(self, limit: int, lease_seconds: float) -> tuple[ActivityRequest, ...]:
        now_dt = datetime.now(UTC)
        now = now_dt.isoformat()
        lease = (now_dt + timedelta(seconds=lease_seconds)).isoformat()
        with self.transaction() as connection:
            processing = int(
                connection.execute(
                    f"SELECT count(*) FROM activities WHERE kind = 'tool' AND status = {ACT_PROCESSING}"
                ).fetchone()[0]
            )
            available = max(0, limit - processing)
            if available == 0:
                return ()
            rows = connection.execute(
                "SELECT a.* FROM activities a JOIN tasks t ON t.task_id = a.task_id "
                f"WHERE a.kind = 'tool' AND a.status = {ACT_PENDING} AND t.status = {TASK_ACTIVE} "
                "ORDER BY a.priority DESC, a.created_at"
            ).fetchall()
            result: list[ActivityRequest] = []
            for row in rows:
                connection.execute(
                    f"UPDATE activities SET status = {ACT_PROCESSING}, lease_until = ?, updated_at = ? "
                    "WHERE activity_id = ?",
                    (lease, now, row["activity_id"]),
                )
                updated = connection.execute(
                    "SELECT * FROM activities WHERE activity_id = ?", (row["activity_id"],)
                ).fetchone()
                if updated is None:
                    raise RuntimeError(_Msg.ACTIVITY_ROW_MISSING.format(activity_id=row["activity_id"]))
                result.append(self._activity(updated))
                if len(result) >= available:
                    break
            return tuple(result)

    def tool_recovery_activities(self) -> tuple[ActivityRequest, ...]:
        now = utc_now()
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT a.* FROM activities a JOIN tasks t ON t.task_id = a.task_id "
                f"WHERE a.kind = 'tool' AND a.status = {ACT_PROCESSING} "
                f"AND (a.lease_until IS NULL OR a.lease_until <= ?) "
                f"AND t.status = {TASK_ACTIVE} ORDER BY a.priority DESC, a.created_at",
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
            self._insert_causal_event(
                connection,
                event_type=message_type,
                summary=message_type,
                payload=payload,
                task_id=str(row["task_id"]),
                agent_id=str(row["agent_id"]),
                causation_id=activity_id,
                correlation_id=str(row["task_id"]),
                now=now,
            )

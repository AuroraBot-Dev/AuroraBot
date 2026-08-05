"""持久化 Inbox、防抖批次与 Triage 决策事务。"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from src.contracts.agent import AgentStatus, TaskLimits, TaskStatus
from src.contracts.amp import AmpEnvelope
from src.contracts.triage import InboxEvent, TriageAction, TriageBatch, TriageDecision, TriageLimits

from .base import RuntimeStoreBase, _json, utc_now


class StoreTriageMixin(RuntimeStoreBase):
    """AMP 在创建 Task 之前的唯一持久化入口。"""

    def enqueue_inbox(self, amp: AmpEnvelope, limits: TriageLimits) -> bool:
        """幂等写入事件，并为同会话 pending 批次刷新 quiet window。"""
        now_dt = datetime.now(UTC)
        now = now_dt.isoformat()
        event_id = amp.header.message_id
        with self.transaction() as connection:
            if connection.execute(
                "SELECT 1 FROM causal_events WHERE external_message_id = ?",
                (event_id,),
            ).fetchone():
                return False
            self._insert_causal_event(
                connection,
                event_type="ingress.received",
                summary=amp.payload.summary,
                payload={
                    "session_id": amp.payload.session_id,
                    "source": amp.header.source,
                    "type": amp.payload.type,
                },
                correlation_id=amp.payload.session_id,
                external_message_id=event_id,
                now=now,
            )
            first_row = connection.execute(
                "SELECT min(created_at) FROM inbox_events WHERE session_id = ? AND status IN ('PENDING', 'DEFERRED')",
                (amp.payload.session_id,),
            ).fetchone()
            first_at = datetime.fromisoformat(first_row[0]) if first_row and first_row[0] else now_dt
            deadline = min(
                now_dt + timedelta(seconds=limits.quiet_seconds),
                first_at + timedelta(seconds=limits.max_wait_seconds),
            ).isoformat()
            connection.execute(
                "UPDATE inbox_events SET status='PENDING', available_at=?, updated_at=? "
                "WHERE session_id=? AND status IN ('PENDING', 'DEFERRED')",
                (deadline, now, amp.payload.session_id),
            )
            connection.execute(
                "INSERT INTO inbox_events VALUES (?, ?, ?, ?, ?, ?, ?, 'PENDING', NULL, ?, ?, ?)",
                (
                    event_id,
                    amp.payload.session_id,
                    amp.payload.type,
                    amp.payload.summary,
                    _json(amp.header.source),
                    _json(amp.payload.data),
                    10 if amp.payload.type == "system.tick" else 100,
                    deadline,
                    now,
                    now,
                ),
            )
        return True

    def claim_triage_batches(self, limits: TriageLimits, limit: int) -> tuple[TriageBatch, ...]:
        """领取到期会话批次；模型 I/O 在事务外进行。"""
        batches: list[TriageBatch] = []
        now = utc_now()
        with self.transaction() as connection:
            sessions = connection.execute(
                "SELECT session_id, min(created_at) AS first_at, max(priority) AS priority "
                "FROM inbox_events WHERE status IN ('PENDING', 'DEFERRED') AND available_at <= ? "
                "GROUP BY session_id ORDER BY priority DESC, first_at LIMIT ?",
                (now, limit),
            ).fetchall()
            for session in sessions:
                rows = connection.execute(
                    "SELECT * FROM inbox_events WHERE session_id = ? "
                    "AND status IN ('PENDING', 'DEFERRED') AND available_at <= ? "
                    "ORDER BY created_at, event_id LIMIT ?",
                    (session["session_id"], now, limits.max_batch_events),
                ).fetchall()
                event_budget = max(
                    300,
                    limits.max_batch_characters - len(str(session["session_id"])) - 500,
                )
                selected = self._bounded_events(rows, event_budget)
                if not selected:
                    continue
                batch_id = str(uuid4())
                placeholders = ",".join("?" for _ in selected)
                connection.execute(
                    f"UPDATE inbox_events SET status='TRIAGING', batch_id=?, updated_at=? "
                    f"WHERE event_id IN ({placeholders})",
                    (batch_id, now, *(event.event_id for event in selected)),
                )
                batches.append(
                    TriageBatch(
                        batch_id=batch_id,
                        session_id=str(session["session_id"]),
                        events=selected,
                        first_received_at=min(event.created_at for event in selected),
                    )
                )
        return tuple(batches)

    def apply_triage(
        self,
        batch: TriageBatch,
        decision: TriageDecision,
        *,
        root_profile: str,
        interactive_budget: TaskLimits,
        autonomous_budget: TaskLimits,
        priority: int,
    ) -> str | None:
        """原子记录 Triage 决定，并 defer、删除或创建一个 Root Task。"""
        now_dt = datetime.now(UTC)
        now = now_dt.isoformat()
        with self.transaction() as connection:
            rows = connection.execute(
                "SELECT * FROM inbox_events WHERE batch_id = ? AND status = 'TRIAGING' ORDER BY created_at, event_id",
                (batch.batch_id,),
            ).fetchall()
            if not rows:
                return None
            event_ids = [str(row["event_id"]) for row in rows]
            self._insert_causal_event(
                connection,
                event_type=f"triage.{decision.action.value}",
                summary=decision.summary,
                payload={"decision": decision.to_dict(), "event_ids": event_ids},
                correlation_id=batch.batch_id,
                now=now,
            )
            if decision.action == TriageAction.DEFER:
                available_at = (now_dt + timedelta(seconds=decision.defer_seconds or 1.0)).isoformat()
                connection.execute(
                    "UPDATE inbox_events SET status='DEFERRED', batch_id=NULL, available_at=?, updated_at=? "
                    "WHERE batch_id=?",
                    (available_at, now, batch.batch_id),
                )
                return None
            if decision.action == TriageAction.DISCARD:
                connection.execute("DELETE FROM inbox_events WHERE batch_id = ?", (batch.batch_id,))
                return None
            task_id = self._create_admitted_task(
                connection,
                batch,
                decision,
                rows,
                root_profile=root_profile,
                interactive_budget=interactive_budget,
                autonomous_budget=autonomous_budget,
                priority=priority,
                now=now,
            )
            connection.execute("DELETE FROM inbox_events WHERE batch_id = ?", (batch.batch_id,))
            return task_id

    def _create_admitted_task(
        self,
        connection: Any,
        batch: TriageBatch,
        decision: TriageDecision,
        rows: list[Any],
        *,
        root_profile: str,
        interactive_budget: TaskLimits,
        autonomous_budget: TaskLimits,
        priority: int,
        now: str,
    ) -> str:
        task_id = str(uuid4())
        agent_id = str(uuid4())
        autonomous = all(str(row["type"]) == "system.tick" for row in rows)
        budget = autonomous_budget if autonomous else interactive_budget
        connection.execute(
            "INSERT INTO tasks (task_id, root_agent_id, root_message_id, session_id, audience_ref, root_summary, "
            "autonomous, status, model_calls, tool_calls, max_model_calls, max_tool_calls, max_duration_seconds, "
            "started_at, updated_at, termination_reason) "
            "VALUES (?, ?, ?, ?, 'global', ?, ?, ?, 0, 0, ?, ?, ?, ?, ?, NULL)",
            (
                task_id,
                agent_id,
                batch.batch_id,
                batch.session_id,
                decision.summary,
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
            (agent_id, task_id, root_profile, decision.summary, AgentStatus.READY, now, now, decision.summary),
        )
        events = [
            {
                "event_id": event.event_id,
                "type": event.type,
                "summary": event.summary,
                "source": event.source,
                "data": event.data,
                "created_at": event.created_at,
            }
            for event in batch.events
        ]
        payload = {"events": events, "triage": decision.to_dict()}
        self._insert_message(
            connection,
            task_id=task_id,
            target_agent_id=agent_id,
            message_type="task.started",
            payload=payload,
            causation_id=batch.batch_id,
            correlation_id=task_id,
            priority=priority,
            now=now,
        )
        self._insert_causal_event(
            connection,
            event_type="task.started",
            summary=decision.summary,
            payload={"event_ids": [event["event_id"] for event in events], "triage": decision.to_dict()},
            task_id=task_id,
            agent_id=agent_id,
            causation_id=batch.batch_id,
            correlation_id=task_id,
            now=now,
        )
        return task_id

    @staticmethod
    def _bounded_events(rows: list[Any], max_characters: int) -> tuple[InboxEvent, ...]:
        selected: list[InboxEvent] = []
        used = 0
        for row in rows:
            event = InboxEvent(
                event_id=str(row["event_id"]),
                session_id=str(row["session_id"]),
                type=str(row["type"]),
                summary=str(row["summary"]),
                source=json.loads(row["source_json"]),
                data=json.loads(row["data_json"]),
                created_at=str(row["created_at"]),
                priority=int(row["priority"]),
            )
            size = len(_json(event.to_dict()))
            if not selected and size > max_characters:
                event = StoreTriageMixin._clipped_event(event, max_characters)
                size = len(_json(event.to_dict()))
            if selected and used + size > max_characters:
                break
            selected.append(event)
            used += size
        return tuple(selected)

    @staticmethod
    def _clipped_event(event: InboxEvent, max_characters: int) -> InboxEvent:
        """让单条超大事件也服从批次字符上界。"""
        data = _json(event.data)
        summary_limit = min(len(event.summary), max(80, max_characters // 8))
        summary = event.summary[:summary_limit]
        preview_budget = max(0, max_characters - len(summary) - 500)
        clipped = InboxEvent(
            event_id=event.event_id,
            session_id=event.session_id,
            type=event.type,
            summary=summary,
            source=event.source,
            data={"truncated": True, "json_preview": data[:preview_budget]},
            created_at=event.created_at,
            priority=event.priority,
        )
        while len(_json(clipped.to_dict())) > max_characters and preview_budget > 0:
            preview_budget //= 2
            clipped = InboxEvent(
                event_id=clipped.event_id,
                session_id=clipped.session_id,
                type=clipped.type,
                summary=clipped.summary,
                source=clipped.source,
                data={"truncated": True, "json_preview": data[:preview_budget]},
                created_at=clipped.created_at,
                priority=clipped.priority,
            )
        return clipped

    def has_due_inbox(self) -> bool:
        with self.connect() as connection:
            return bool(
                connection.execute(
                    "SELECT 1 FROM inbox_events WHERE status IN ('PENDING', 'DEFERRED') AND available_at <= ? LIMIT 1",
                    (utc_now(),),
                ).fetchone()
            )

    def inbox_delay_seconds(self) -> float | None:
        now = datetime.now(UTC)
        with self.connect() as connection:
            row = connection.execute(
                "SELECT min(available_at) FROM inbox_events WHERE status IN ('PENDING', 'DEFERRED')"
            ).fetchone()
        if row is None or row[0] is None:
            return None
        return max(0.0, (datetime.fromisoformat(str(row[0])) - now).total_seconds())

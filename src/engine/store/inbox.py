"""持久化 Inbox、防抖批次、会话 generation 与入口 Triage Task（Schema v10，SQLAlchemy ORM 实现）。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from sqlalchemy import delete, func, select, update

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

from src.contracts import (
    AgentStatus,
    AmpEnvelope,
    InboxEvent,
    TaskLimits,
    TaskStatus,
    TriageBatch,
    TriageLimits,
)
from src.utils import bounded_summary

from .base import RuntimeStoreBase, _json, _loads, utc_now
from .models import (
    INBOX_DEFERRED,
    INBOX_PENDING,
    INBOX_TRIAGING,
    AgentRow,
    CausalEventRow,
    InboxEventRow,
    SessionLaneRow,
    TaskRow,
)


class StoreInboxMixin(RuntimeStoreBase):
    """AMP 在入口 triage Task 之前的唯一持久化入口。"""

    def enqueue_inbox(self, amp: AmpEnvelope, limits: TriageLimits) -> bool:
        """幂等写入事件，并为同会话 pending 批次刷新 quiet window。"""
        now = utc_now()
        now_dt = datetime.fromisoformat(now)
        event_id = amp.header.message_id
        with self.session() as session:
            if (
                session.scalar(
                    select(CausalEventRow.event_id).where(
                        CausalEventRow.correlation_id == event_id,
                        CausalEventRow.event_type == "ingress.received",
                    )
                )
                is not None
            ):
                return False
            lane = session.get(SessionLaneRow, amp.payload.session_id)
            if lane is None:
                lane = SessionLaneRow(
                    session_id=amp.payload.session_id,
                    observed_revision=0,
                    generation_revision=0,
                    committed_revision=0,
                    generation_watermark=0,
                    active_task_id=None,
                    interrupt_count=0,
                    generation_started_at=None,
                    updated_at=now,
                )
                session.add(lane)
            lane.observed_revision += 1
            lane.updated_at = now
            revision = int(lane.observed_revision)
            priority = _amp_priority(amp)
            self._insert_causal_event(
                session,
                event_type="ingress.received",
                summary=amp.payload.summary,
                payload={
                    "session_id": amp.payload.session_id,
                    "source": amp.header.source,
                    "type": amp.payload.type,
                    "revision": revision,
                },
                correlation_id=event_id,
                now=now,
            )
            first_at = session.scalar(
                select(func.min(InboxEventRow.created_at)).where(
                    InboxEventRow.session_id == amp.payload.session_id,
                    InboxEventRow.status.in_((INBOX_PENDING, INBOX_DEFERRED)),
                )
            )
            first_dt = datetime.fromisoformat(first_at) if first_at else now_dt
            deadline = min(
                now_dt + timedelta(seconds=limits.quiet_seconds),
                first_dt + timedelta(seconds=limits.max_wait_seconds),
            ).isoformat()
            session.execute(
                update(InboxEventRow)
                .where(
                    InboxEventRow.session_id == amp.payload.session_id,
                    InboxEventRow.status.in_((INBOX_PENDING, INBOX_DEFERRED)),
                )
                .values(status=INBOX_PENDING, available_at=deadline, updated_at=now)
            )
            session.add(
                InboxEventRow(
                    event_id=event_id,
                    session_id=amp.payload.session_id,
                    event_type=amp.payload.type,
                    summary=amp.payload.summary,
                    source_json=_json(amp.header.source),
                    data_json=_json(amp.payload.data),
                    priority=priority,
                    status=INBOX_PENDING,
                    batch_id=None,
                    available_at=deadline,
                    created_at=now,
                    updated_at=now,
                    revision=revision,
                )
            )
        return True

    def has_due_inbox(self) -> bool:
        with self.session() as session:
            row = session.scalar(
                select(InboxEventRow.event_id)
                .join(SessionLaneRow, SessionLaneRow.session_id == InboxEventRow.session_id)
                .where(
                    InboxEventRow.status.in_((INBOX_PENDING, INBOX_DEFERRED)),
                    InboxEventRow.available_at <= utc_now(),
                    SessionLaneRow.active_task_id.is_(None),
                )
                .limit(1)
            )
            return row is not None

    def inbox_delay_seconds(self) -> float | None:
        now = datetime.now(UTC)
        with self.session() as session:
            first_at = session.scalar(
                select(func.min(InboxEventRow.available_at))
                .join(SessionLaneRow, SessionLaneRow.session_id == InboxEventRow.session_id)
                .where(
                    InboxEventRow.status.in_((INBOX_PENDING, INBOX_DEFERRED)),
                    SessionLaneRow.active_task_id.is_(None),
                )
            )
        if first_at is None:
            return None
        return max(0.0, (datetime.fromisoformat(str(first_at)) - now).total_seconds())

    def claim_triage_batches(self, limits: TriageLimits, limit: int) -> tuple[TriageBatch, ...]:
        """领取到期会话批次；模型 I/O 在事务外进行。"""
        batches: list[TriageBatch] = []
        now = utc_now()
        with self.session() as session:
            session_rows = session.execute(
                select(
                    InboxEventRow.session_id,
                    func.min(InboxEventRow.created_at).label("first_at"),
                    func.max(InboxEventRow.priority).label("priority"),
                )
                .where(InboxEventRow.status.in_((INBOX_PENDING, INBOX_DEFERRED)), InboxEventRow.available_at <= now)
                .join(SessionLaneRow, SessionLaneRow.session_id == InboxEventRow.session_id)
                .where(SessionLaneRow.active_task_id.is_(None))
                .group_by(InboxEventRow.session_id)
                .order_by(func.max(InboxEventRow.priority).desc(), "first_at")
                .limit(limit)
            ).all()
            for session_id, *_ in session_rows:
                rows = session.execute(
                    select(InboxEventRow)
                    .where(
                        InboxEventRow.session_id == session_id,
                        InboxEventRow.status.in_((INBOX_PENDING, INBOX_DEFERRED)),
                        InboxEventRow.available_at <= now,
                    )
                    .order_by(InboxEventRow.created_at, InboxEventRow.event_id)
                    .limit(limits.max_batch_events)
                ).scalars()
                event_budget = max(300, limits.max_batch_characters - len(str(session_id)) - 500)
                selected = self._bounded_events(tuple(rows), event_budget)
                if not selected:
                    continue
                batch_id = str(uuid4())
                session.execute(
                    update(InboxEventRow)
                    .where(InboxEventRow.event_id.in_([event.event_id for event in selected]))
                    .values(status=INBOX_TRIAGING, batch_id=batch_id, updated_at=now)
                )
                batches.append(
                    TriageBatch(
                        batch_id=batch_id,
                        session_id=str(session_id),
                        events=selected,
                        first_received_at=min(event.created_at for event in selected),
                        generation_revision=max(event.revision for event in selected),
                    )
                )
        return tuple(batches)

    def create_triage_task(
        self,
        batch: TriageBatch,
        *,
        triage_profile: str,
        interactive_budget: TaskLimits,
        autonomous_budget: TaskLimits,
        priority: int,
    ) -> tuple[str, str] | None:
        """防抖批次到期后创建 Task 与入口 triage agent。

        批次原始事件保留在 Inbox，由 triage agent 的决策在 apply_decision
        中结算；批次投影存入入口 agent 状态，供委派时向子 Agent 传递。
        """
        now = utc_now()
        with self.session() as session:
            lane = session.get(SessionLaneRow, batch.session_id)
            if lane is None:
                lane = SessionLaneRow(
                    session_id=batch.session_id,
                    observed_revision=batch.generation_revision,
                    generation_revision=0,
                    committed_revision=0,
                    generation_watermark=0,
                    active_task_id=None,
                    interrupt_count=0,
                    generation_started_at=None,
                    updated_at=now,
                )
                session.add(lane)
            if lane.active_task_id is not None:
                session.execute(
                    update(InboxEventRow)
                    .where(InboxEventRow.batch_id == batch.batch_id)
                    .values(status=INBOX_PENDING, batch_id=None, updated_at=now)
                )
                return None
            rows = (
                session.execute(
                    select(InboxEventRow)
                    .where(InboxEventRow.batch_id == batch.batch_id, InboxEventRow.status == INBOX_TRIAGING)
                    .order_by(InboxEventRow.created_at, InboxEventRow.event_id)
                )
                .scalars()
                .all()
            )
            if not rows:
                return None
            task_id = str(uuid4())
            agent_id = str(uuid4())
            autonomous = all(str(row.event_type) == "system.tick" for row in rows)
            budget = autonomous_budget if autonomous else interactive_budget
            summary = bounded_summary([event.summary for event in batch.events])
            session.add(
                TaskRow(
                    task_id=task_id,
                    root_agent_id=agent_id,
                    root_message_id=batch.batch_id,
                    session_id=batch.session_id,
                    root_summary=summary,
                    autonomous=int(autonomous),
                    status=TaskStatus.ACTIVE,
                    model_calls=0,
                    tool_calls=0,
                    max_model_calls=budget.max_model_calls,
                    max_tool_calls=budget.max_tool_calls,
                    max_duration_seconds=budget.max_duration_seconds,
                    started_at=now,
                    updated_at=now,
                    termination_reason=None,
                )
            )
            if not autonomous:
                lane.active_task_id = task_id
                lane.generation_revision = batch.generation_revision
                lane.generation_watermark = batch.generation_revision
                lane.generation_started_at = lane.generation_started_at or now
                lane.updated_at = now
            events = _event_projection(batch.events)
            session.add(
                AgentRow(
                    agent_id=agent_id,
                    task_id=task_id,
                    parent_agent_id=None,
                    profile_id=triage_profile,
                    depth=0,
                    assignment="triage",
                    status=AgentStatus.READY,
                    state_json=_json({"batch_events": events}),
                    created_at=now,
                    updated_at=now,
                    last_summary=summary,
                )
            )
            self._insert_message(
                session,
                task_id=task_id,
                target_agent_id=agent_id,
                message_type="task.started",
                payload={"batch": batch.to_dict()},
                causation_id=batch.batch_id,
                correlation_id=task_id,
                priority=priority,
                now=now,
            )
            self._insert_causal_event(
                session,
                event_type="task.started",
                summary=summary,
                payload={"batch_id": batch.batch_id, "event_ids": [event["event_id"] for event in events]},
                task_id=task_id,
                agent_id=agent_id,
                causation_id=batch.batch_id,
                correlation_id=task_id,
                now=now,
            )
        return task_id, summary

    @staticmethod
    def settle_batch(
        session: Session,
        batch_id: str,
        mode: str,
        now: str,
        defer_seconds: float | None = None,
    ) -> None:
        """按 triage 决策结算批次：defer 回到 DEFERRED，delete 移除原始事件。"""
        if mode == "defer":
            available_at = (datetime.now(UTC) + timedelta(seconds=max(0.0, defer_seconds or 0.0))).isoformat()
            session.execute(
                update(InboxEventRow)
                .where(InboxEventRow.batch_id == batch_id)
                .values(status=INBOX_DEFERRED, batch_id=None, available_at=available_at, updated_at=now)
            )
        else:
            session.execute(delete(InboxEventRow).where(InboxEventRow.batch_id == batch_id))

    @staticmethod
    def _bounded_events(rows: tuple[Any, ...], max_characters: int) -> tuple[InboxEvent, ...]:
        selected: list[InboxEvent] = []
        used = 0
        for row in rows:
            event = InboxEvent(
                event_id=str(row.event_id),
                session_id=str(row.session_id),
                type=str(row.event_type),
                summary=str(row.summary),
                source=_loads(row.source_json),
                data=_loads(row.data_json),
                created_at=str(row.created_at),
                priority=int(row.priority),
                revision=int(row.revision),
            )
            size = len(_json(event.to_dict()))
            if not selected and size > max_characters:
                event = StoreInboxMixin._clipped_event(event, max_characters)
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
            revision=event.revision,
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
                revision=clipped.revision,
            )
        return clipped


def _event_projection(events: tuple[InboxEvent, ...]) -> list[dict[str, Any]]:
    """批次事件的规范投影，供入口 agent 状态与委派传递复用。"""
    return [
        {
            "event_id": event.event_id,
            "type": event.type,
            "summary": event.summary,
            "source": event.source,
            "data": event.data,
            "created_at": event.created_at,
            "revision": event.revision,
        }
        for event in events
    ]


def _amp_priority(amp: AmpEnvelope) -> int:
    if amp.payload.type == "system.tick":
        return 10
    data = amp.payload.data
    attention = data.get("attention")
    if attention in {"direct", "correction", "urgent"} or any(
        data.get(name) is True for name in ("directed", "mentioned", "reply_to_bot")
    ):
        return 200
    return 100

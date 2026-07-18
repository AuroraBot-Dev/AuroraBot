from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from src.kernel.contracts import AgentDecision, Completion, TaskState, TaskStatus
from src.kernel.memory import MemoryFailure, MemoryProposal, MemoryQuery, MemoryResult
from src.localhost.configuration import SchedulerConfig
from src.localhost.scheduler import CognitiveScheduler

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


def task(clock: Callable[[], datetime], *, status: TaskStatus = TaskStatus.ACTIVE, tool_calls: int = 0) -> TaskState:
    now = clock().isoformat()
    return TaskState(
        task_id="task",
        root_agent_id="agent",
        root_message_id="message",
        session_id="session",
        root_summary="summary",
        autonomous=True,
        status=status,
        model_calls=0,
        tool_calls=tool_calls,
        max_model_calls=3,
        max_tool_calls=2,
        max_duration_seconds=120,
        started_at=now,
        updated_at=now,
    )


def test_scheduler_tracks_terminal_autonomous_tasks(tmp_path: Path) -> None:
    current = datetime(2026, 7, 19, tzinfo=UTC)

    def clock() -> datetime:
        return current

    scheduler = CognitiveScheduler(tmp_path / "scheduler.json", SchedulerConfig(), now=clock)
    assert not scheduler.can_tick((task(clock),))
    completed = task(clock, status=TaskStatus.COMPLETED, tool_calls=1)
    scheduler.reconcile((completed,))
    assert scheduler.state.accounted_task_ids == ["task"]
    assert scheduler.state.current_interval_seconds == scheduler.configuration.action_cooldown_seconds


def test_scheduler_silence_backs_off_and_daily_quota_resets(tmp_path: Path) -> None:
    current = datetime(2026, 7, 19, tzinfo=UTC)

    def clock() -> datetime:
        return current

    scheduler = CognitiveScheduler(tmp_path / "scheduler.json", SchedulerConfig(), now=clock)
    scheduler.reconcile((task(clock, status=TaskStatus.SILENT),))
    assert scheduler.state.current_interval_seconds == 60
    assert scheduler.reserve_autonomous_model_call()
    current += timedelta(days=1)
    scheduler.status()
    assert scheduler.state.autonomous_model_calls == 0
    assert scheduler.state.accounted_task_ids == []


def test_agent_decision_and_memory_placeholder_contracts() -> None:
    decision = AgentDecision(completion=Completion("done", ({"uri": "artifact"},)))
    assert decision.completion is not None
    assert MemoryQuery("who", "global").limit == 8
    assert MemoryResult(()).items == ()
    assert MemoryProposal({"fact": "x"}, "task").importance == 0.5
    assert MemoryFailure().code == "memory.unavailable"

"""Persistent adaptive autonomous rhythm for the localhost runtime."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from src.contracts.agent import TaskState, TaskStatus
from src.utils.log_utils import get_logger
from src.utils.serialization import atomic_write_json, read_json

logger = get_logger("aurora.scheduler")

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from src.contracts.configuration import SchedulerConfig


@dataclass(slots=True)
class SchedulerState:
    next_tick_at: str
    current_interval_seconds: float
    utc_day: str
    autonomous_model_calls: int = 0
    autonomous_tokens: int = 0
    accounted_task_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class CognitiveScheduler:
    def __init__(
        self,
        path: Path,
        configuration: SchedulerConfig,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.path = path
        self.configuration = configuration
        self.now = now or (lambda: datetime.now(UTC))
        self.state = self._load()

    def _load(self) -> SchedulerState:
        if self.path.exists():
            value = read_json(self.path)
            if isinstance(value, dict):
                try:
                    state = SchedulerState(**value)
                    self._roll_day(state)
                    logger.debug(
                        "scheduler state restored path=%s next_tick_at=%s interval_s=%.1f calls=%d tokens=%d",
                        self.path,
                        state.next_tick_at,
                        state.current_interval_seconds,
                        state.autonomous_model_calls,
                        state.autonomous_tokens,
                    )
                    return state
                except (TypeError, ValueError):
                    logger.warning("invalid scheduler state replaced path=%s", self.path)
        now = self.now()
        state = SchedulerState(
            next_tick_at=(now + timedelta(seconds=self.configuration.idle_initial_seconds)).isoformat(),
            current_interval_seconds=self.configuration.idle_initial_seconds,
            utc_day=now.date().isoformat(),
        )
        self._save(state)
        logger.debug(
            "scheduler state initialized path=%s next_tick_at=%s interval_s=%.1f",
            self.path,
            state.next_tick_at,
            state.current_interval_seconds,
        )
        return state

    def _save(self, state: SchedulerState | None = None) -> None:
        if state is not None:
            self.state = state
        atomic_write_json(self.path, self.state.to_dict())

    def _roll_day(self, state: SchedulerState | None = None) -> None:
        target = state or self.state
        today = self.now().date().isoformat()
        if target.utc_day != today:
            previous_day = target.utc_day
            target.utc_day = today
            target.autonomous_model_calls = 0
            target.autonomous_tokens = 0
            target.accounted_task_ids.clear()
            logger.info("scheduler daily quota reset previous_day=%s utc_day=%s", previous_day, today)

    def on_external_activity(self) -> None:
        self._roll_day()
        self.state.current_interval_seconds = self.configuration.idle_initial_seconds
        self.state.next_tick_at = (self.now() + timedelta(seconds=self.configuration.idle_initial_seconds)).isoformat()
        self._save()
        logger.debug(
            "scheduler reset by external activity next_tick_at=%s interval_s=%.1f",
            self.state.next_tick_at,
            self.state.current_interval_seconds,
        )

    def can_tick(self, tasks: tuple[TaskState, ...]) -> bool:
        self._roll_day()
        if not self.configuration.enabled:
            return False
        if any(task.autonomous and not task.terminal for task in tasks):
            return False
        if self.state.autonomous_model_calls >= self.configuration.autonomous_daily_model_calls:
            return False
        if self.state.autonomous_tokens >= self.configuration.autonomous_daily_tokens:
            return False
        return self.now() >= datetime.fromisoformat(self.state.next_tick_at)

    def mark_tick_emitted(self) -> None:
        # Prevent duplicate ticks while the emitted event waits for ingestion.
        self.state.next_tick_at = (self.now() + timedelta(seconds=self.configuration.idle_max_seconds)).isoformat()
        self._save()
        logger.debug("scheduler tick reserved next_tick_at=%s", self.state.next_tick_at)

    def reconcile(self, tasks: tuple[TaskState, ...]) -> None:
        self._roll_day()
        changed = False
        accounted = set(self.state.accounted_task_ids)
        today = self.now().date()
        for task in tasks:
            if not task.autonomous or not task.terminal or task.task_id in accounted:
                continue
            if datetime.fromisoformat(task.updated_at).astimezone(UTC).date() != today:
                continue
            self.state.accounted_task_ids.append(task.task_id)
            accounted.add(task.task_id)
            if task.status == TaskStatus.COMPLETED or task.tool_calls > 0:
                interval = self.configuration.action_cooldown_seconds
            else:
                interval = min(
                    self.configuration.idle_max_seconds,
                    self.state.current_interval_seconds * self.configuration.idle_multiplier,
                )
            self.state.current_interval_seconds = interval
            self.state.next_tick_at = (self.now() + timedelta(seconds=interval)).isoformat()
            changed = True
            logger.info(
                "autonomous Task accounted task_id=%s status=%s tool_calls=%d next_interval_s=%.1f next_tick_at=%s",
                task.task_id,
                task.status,
                task.tool_calls,
                interval,
                self.state.next_tick_at,
            )
        if changed:
            self._save()

    def status(self) -> dict[str, object]:
        self._roll_day()
        return self.state.to_dict()

    def reserve_autonomous_model_call(self) -> bool:
        self._roll_day()
        if self.state.autonomous_model_calls >= self.configuration.autonomous_daily_model_calls:
            logger.warning(
                "autonomous model call quota exhausted calls=%d limit=%d",
                self.state.autonomous_model_calls,
                self.configuration.autonomous_daily_model_calls,
            )
            return False
        if self.state.autonomous_tokens >= self.configuration.autonomous_daily_tokens:
            logger.warning(
                "autonomous token quota exhausted tokens=%d limit=%d",
                self.state.autonomous_tokens,
                self.configuration.autonomous_daily_tokens,
            )
            return False
        self.state.autonomous_model_calls += 1
        self._save()
        logger.debug(
            "autonomous model call reserved calls=%d limit=%d",
            self.state.autonomous_model_calls,
            self.configuration.autonomous_daily_model_calls,
        )
        return True

    def record_autonomous_tokens(self, tokens: int) -> None:
        self._roll_day()
        self.state.autonomous_tokens += max(0, tokens)
        self._save()
        logger.debug(
            "autonomous tokens recorded delta=%d total=%d limit=%d",
            max(0, tokens),
            self.state.autonomous_tokens,
            self.configuration.autonomous_daily_tokens,
        )

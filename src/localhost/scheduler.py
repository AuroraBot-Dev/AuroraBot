"""Persistent adaptive autonomous rhythm for the localhost runtime."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from src.kernel.episodes import EpisodeSnapshot, EpisodeStatus
from src.utils.serialization import atomic_write_json, read_json

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from src.localhost.configuration import SchedulerConfig


@dataclass(slots=True)
class SchedulerState:
    next_tick_at: str
    current_interval_seconds: float
    utc_day: str
    autonomous_model_calls: int = 0
    autonomous_tokens: int = 0
    accounted_episode_ids: list[str] = field(default_factory=list)

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
                    return state
                except (TypeError, ValueError):
                    pass
        now = self.now()
        state = SchedulerState(
            next_tick_at=(now + timedelta(seconds=self.configuration.idle_initial_seconds)).isoformat(),
            current_interval_seconds=self.configuration.idle_initial_seconds,
            utc_day=now.date().isoformat(),
        )
        self._save(state)
        return state

    def _save(self, state: SchedulerState | None = None) -> None:
        if state is not None:
            self.state = state
        atomic_write_json(self.path, self.state.to_dict())

    def _roll_day(self, state: SchedulerState | None = None) -> None:
        target = state or self.state
        today = self.now().date().isoformat()
        if target.utc_day != today:
            target.utc_day = today
            target.autonomous_model_calls = 0
            target.autonomous_tokens = 0
            target.accounted_episode_ids.clear()

    def on_external_activity(self) -> None:
        self._roll_day()
        self.state.current_interval_seconds = self.configuration.idle_initial_seconds
        self.state.next_tick_at = (self.now() + timedelta(seconds=self.configuration.idle_initial_seconds)).isoformat()
        self._save()

    def can_tick(self, episodes: tuple[EpisodeSnapshot, ...]) -> bool:
        self._roll_day()
        if not self.configuration.enabled:
            return False
        if any(episode.autonomous and not episode.terminal for episode in episodes):
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

    def reconcile(self, episodes: tuple[EpisodeSnapshot, ...]) -> None:
        self._roll_day()
        changed = False
        accounted = set(self.state.accounted_episode_ids)
        for episode in episodes:
            if not episode.autonomous or not episode.terminal or episode.episode_id in accounted:
                continue
            self.state.accounted_episode_ids.append(episode.episode_id)
            accounted.add(episode.episode_id)
            if episode.status == EpisodeStatus.COMPLETED or episode.tool_calls > 0:
                interval = self.configuration.action_cooldown_seconds
            else:
                interval = min(
                    self.configuration.idle_max_seconds,
                    self.state.current_interval_seconds * self.configuration.idle_multiplier,
                )
            self.state.current_interval_seconds = interval
            self.state.next_tick_at = (self.now() + timedelta(seconds=interval)).isoformat()
            changed = True
        if changed:
            self._save()

    def status(self) -> dict[str, object]:
        self._roll_day()
        return self.state.to_dict()

    def reserve_autonomous_model_call(self) -> bool:
        self._roll_day()
        if self.state.autonomous_model_calls >= self.configuration.autonomous_daily_model_calls:
            return False
        if self.state.autonomous_tokens >= self.configuration.autonomous_daily_tokens:
            return False
        self.state.autonomous_model_calls += 1
        self._save()
        return True

    def record_autonomous_tokens(self, tokens: int) -> None:
        self._roll_day()
        self.state.autonomous_tokens += max(0, tokens)
        self._save()

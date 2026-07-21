"""Persistent Runtime-owned daily quota for autonomous model work."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from src.utils.log_utils import get_logger
from src.utils.serialization import atomic_write_json, read_json

logger = get_logger("aurora.autonomy")

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from src.contracts.configuration import AutonomyConfig


@dataclass(slots=True)
class AutonomyQuotaState:
    utc_day: str
    autonomous_model_calls: int = 0
    autonomous_tokens: int = 0

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class AutonomyQuota:
    def __init__(
        self,
        path: Path,
        configuration: AutonomyConfig,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.path = path
        self.configuration = configuration
        self.now = now or (lambda: datetime.now(UTC))
        self.state = self._load()

    def _load(self) -> AutonomyQuotaState:
        if self.path.exists():
            value = read_json(self.path)
            if isinstance(value, dict):
                try:
                    state = AutonomyQuotaState(**value)
                    self._roll_day(state)
                except (TypeError, ValueError):
                    logger.warning("invalid autonomy quota replaced path=%s", self.path)
                else:
                    logger.debug(
                        "autonomy quota restored path=%s calls=%d tokens=%d",
                        self.path,
                        state.autonomous_model_calls,
                        state.autonomous_tokens,
                    )
                    return state
        state = AutonomyQuotaState(utc_day=self.now().date().isoformat())
        self._save(state)
        return state

    def _save(self, state: AutonomyQuotaState | None = None) -> None:
        if state is not None:
            self.state = state
        atomic_write_json(self.path, self.state.to_dict())

    def _roll_day(self, state: AutonomyQuotaState | None = None) -> None:
        target = state or self.state
        today = self.now().date().isoformat()
        if target.utc_day != today:
            previous_day = target.utc_day
            target.utc_day = today
            target.autonomous_model_calls = 0
            target.autonomous_tokens = 0
            logger.info("autonomy quota reset previous_day=%s utc_day=%s", previous_day, today)

    def reserve_model_call(self) -> bool:
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
        return True

    def record_tokens(self, tokens: int) -> None:
        self._roll_day()
        self.state.autonomous_tokens += max(0, tokens)
        self._save()

    def status(self) -> dict[str, object]:
        self._roll_day()
        self._save()
        return self.state.to_dict()

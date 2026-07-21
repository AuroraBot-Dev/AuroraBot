"""Clock service — pure business logic for clock operations.

Provides time retrieval, alarm scheduling, and timer functionality
with in-memory storage. No MCP or platform imports.

用法::

    from service import ClockService
    ClockService.get_current_time()
    ClockService.set_alarm("08:00", label="起床")
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import uuid
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

_BEIJING_TZ = timezone(timedelta(hours=8))

from src.utils.log_utils import get_logger

logger = get_logger("aurora-app-clock.service")

# In-memory storage for alarms and timers
_alarms: dict[str, dict[str, Any]] = {}
_tasks: dict[str, asyncio.Task[None]] = {}
_notify: Callable[[str, dict[str, Any]], Awaitable[None]] | None = None
_HEARTBEAT_ID = "aurora-heartbeat"


def _state_path() -> Path:
    base = Path(os.getenv("AURORA_APP_DATA_DIR", "data/app_data")) / "org.aurora.clock"
    base.mkdir(parents=True, exist_ok=True)
    return base / "tasks.json"


def _save() -> None:
    path = _state_path()
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(list(_alarms.values()), ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


class ClockService:
    """Business logic for clock operations."""

    @staticmethod
    def get_current_time(fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
        """Return the current time formatted according to *fmt*.

        Args:
            fmt: A strftime-compatible format string.
                 Defaults to ``"%Y-%m-%d %H:%M:%S"``.

        Returns:
            Formatted current time string.
        """
        return datetime.now(tz=_BEIJING_TZ).strftime(fmt)

    @staticmethod
    async def initialize(notifier: Callable[[str, dict[str, Any]], Awaitable[None]] | None = None) -> None:
        """Restore pending persisted tasks and install the active MCP notification sender."""
        global _notify  # noqa: PLW0603
        _notify = notifier
        path = _state_path()
        if not path.exists():
            return
        try:
            items = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return
        if not isinstance(items, list):
            return
        now = datetime.now(UTC)
        for item in items:
            if not isinstance(item, dict) or not isinstance(item.get("trigger_at"), str):
                continue
            try:
                due = datetime.fromisoformat(item["trigger_at"])
            except ValueError:
                continue
            if due <= now and item.get("type") != "heartbeat":
                continue
            task_id = str(item.get("id", ""))
            if task_id:
                _alarms[task_id] = item
                ClockService._schedule(item)

    @staticmethod
    def start_heartbeat() -> dict[str, Any]:
        """Restore an existing heartbeat or create the fallback heartbeat for this process."""
        existing = _alarms.get(_HEARTBEAT_ID)
        if existing is not None:
            return existing
        interval = _heartbeat_initial_seconds()
        return ClockService._schedule_heartbeat(interval, interval)

    @staticmethod
    def sleep(seconds: int) -> dict[str, Any]:
        """Replace the fallback heartbeat with the Agent-selected next wake time."""
        if seconds <= 0:
            raise ValueError("seconds must be positive")
        fallback = _heartbeat_initial_seconds()
        existing = _alarms.get(_HEARTBEAT_ID)
        if existing is not None:
            fallback = _positive_number(existing.get("fallback_seconds"), fallback)
        interval = min(_heartbeat_max_seconds(), max(_heartbeat_min_seconds(), float(seconds)))
        return ClockService._schedule_heartbeat(interval, fallback)

    @staticmethod
    async def set_alarm(time_str: str, label: str = "") -> dict[str, Any]:
        """Store an alarm in memory and return its info with a unique id.

        Args:
            time_str: Alarm time as a string (e.g. ``"08:00"`` or ISO format).
            label:    Optional human-readable label.

        Returns:
            Dict with keys: id, time_str, label, type ("alarm").
        """
        alarm_id = uuid.uuid4().hex
        trigger_at = _parse_alarm_time(time_str)
        alarm: dict[str, Any] = {
            "id": alarm_id,
            "time_str": time_str,
            "label": label,
            "type": "alarm",
            "trigger_at": trigger_at.isoformat(),
        }
        _alarms[alarm_id] = alarm
        ClockService._schedule(alarm)
        _save()
        logger.info("alarm scheduled alarm_id=%s label_present=%s", alarm_id, bool(label))
        return alarm

    @staticmethod
    async def set_timer(seconds: int, label: str = "") -> dict[str, Any]:
        """Create an asyncio task that waits *seconds* and return timer info.

        After the delay the timer entry is removed from storage.

        Args:
            seconds: Number of seconds to wait.
            label:   Optional human-readable label.

        Returns:
            Dict with keys: id, seconds, label, type ("timer").
        """
        timer_id = uuid.uuid4().hex
        timer: dict[str, Any] = {
            "id": timer_id,
            "seconds": seconds,
            "label": label,
            "type": "timer",
            "trigger_at": (datetime.now(UTC) + timedelta(seconds=seconds)).isoformat(),
        }
        _alarms[timer_id] = timer
        ClockService._schedule(timer)
        _save()
        logger.info("timer scheduled timer_id=%s label_present=%s", timer_id, bool(label))
        return timer

    @staticmethod
    def _schedule(item: dict[str, Any]) -> None:
        task_id = str(item["id"])
        existing = _tasks.get(task_id)
        if existing is not None and not existing.done():
            return
        due = datetime.fromisoformat(str(item["trigger_at"]))

        async def _wait() -> None:
            emitted = False
            try:
                await asyncio.sleep(max(0.0, (due - datetime.now(UTC)).total_seconds()))
                event_type = {
                    "alarm": "alarm.triggered",
                    "timer": "timer.triggered",
                    "heartbeat": "system.tick",
                }.get(str(item.get("type")), "timer.triggered")
                if _notify is not None:
                    data = {"id": task_id, "label": item.get("label", ""), "trigger_at": item["trigger_at"]}
                    if item.get("type") == "heartbeat":
                        data["interval_seconds"] = item["seconds"]
                    await _notify(event_type, data)
                    emitted = True
            finally:
                if _tasks.get(task_id) is asyncio.current_task():
                    _alarms.pop(task_id, None)
                    _tasks.pop(task_id, None)
                    if item.get("type") == "heartbeat" and emitted:
                        fallback = _positive_number(item.get("fallback_seconds"), _heartbeat_initial_seconds())
                        ClockService._schedule_heartbeat(fallback, fallback)
                    else:
                        _save()

        _tasks[task_id] = asyncio.create_task(_wait())

    @staticmethod
    def list_alarms() -> list[dict[str, Any]]:
        """Return all scheduled alarms and timers.

        Returns:
            List of alarm/timer dicts currently stored in memory.
        """
        return [item for item in _alarms.values() if item.get("type") != "heartbeat"]

    @staticmethod
    def cancel_alarm(alarm_id: str) -> bool:
        """Cancel an alarm or timer by its id.

        Args:
            alarm_id: Unique identifier returned by ``set_alarm`` or
                      ``set_timer``.

        Returns:
            ``True`` if the item was found and cancelled, ``False`` otherwise.
        """
        if alarm_id not in _alarms:
            logger.warning("alarm or timer not found item_id=%s", alarm_id)
            return False

        task = _tasks.get(alarm_id)
        if task is not None and not task.done():
            task.cancel()

        _alarms.pop(alarm_id, None)
        _tasks.pop(alarm_id, None)
        _save()
        logger.info("alarm or timer cancelled item_id=%s", alarm_id)
        return True

    @staticmethod
    def _schedule_heartbeat(seconds: float, fallback_seconds: float) -> dict[str, Any]:
        existing = _tasks.get(_HEARTBEAT_ID)
        if existing is not None and not existing.done():
            existing.cancel()
        _tasks.pop(_HEARTBEAT_ID, None)
        _alarms.pop(_HEARTBEAT_ID, None)
        heartbeat: dict[str, Any] = {
            "id": _HEARTBEAT_ID,
            "seconds": seconds,
            "fallback_seconds": fallback_seconds,
            "type": "heartbeat",
            "trigger_at": (datetime.now(UTC) + timedelta(seconds=seconds)).isoformat(),
        }
        _alarms[_HEARTBEAT_ID] = heartbeat
        ClockService._schedule(heartbeat)
        _save()
        logger.info("heartbeat scheduled interval_s=%.1f", seconds)
        return heartbeat


def _parse_alarm_time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
        return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=_BEIJING_TZ).astimezone(UTC)
    except ValueError:
        match = re.fullmatch(r"(\d{1,2}):(\d{2})", value.strip())
        if match is None:
            raise ValueError("time_str must be ISO-8601 or HH:MM") from None
        now = datetime.now(_BEIJING_TZ)
        due = now.replace(hour=int(match.group(1)), minute=int(match.group(2)), second=0, microsecond=0)
        if due <= now:
            due += timedelta(days=1)
        return due.astimezone(UTC)


def _positive_number(value: object, default: float) -> float:
    if isinstance(value, bool):
        return default
    if not isinstance(value, (int, float, str)):
        return default
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _heartbeat_initial_seconds() -> float:
    return _positive_number(os.getenv("AURORA_CLOCK_HEARTBEAT_INITIAL_SECONDS"), 30.0)


def _heartbeat_min_seconds() -> float:
    return _positive_number(os.getenv("AURORA_CLOCK_HEARTBEAT_MIN_SECONDS"), 30.0)


def _heartbeat_max_seconds() -> float:
    return max(
        _heartbeat_min_seconds(),
        _positive_number(os.getenv("AURORA_CLOCK_HEARTBEAT_MAX_SECONDS"), 1800.0),
    )

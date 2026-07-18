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
            if due <= now:
                continue
            task_id = str(item.get("id", ""))
            if task_id:
                _alarms[task_id] = item
                ClockService._schedule(item)

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
        due = datetime.fromisoformat(str(item["trigger_at"]))

        async def _wait() -> None:
            try:
                await asyncio.sleep(max(0.0, (due - datetime.now(UTC)).total_seconds()))
                event_type = "alarm.triggered" if item.get("type") == "alarm" else "timer.triggered"
                if _notify is not None:
                    await _notify(
                        event_type,
                        {"id": task_id, "label": item.get("label", ""), "trigger_at": item["trigger_at"]},
                    )
            finally:
                _alarms.pop(task_id, None)
                _tasks.pop(task_id, None)
                _save()

        _tasks[task_id] = asyncio.create_task(_wait())

    @staticmethod
    def list_alarms() -> list[dict[str, Any]]:
        """Return all scheduled alarms and timers.

        Returns:
            List of alarm/timer dicts currently stored in memory.
        """
        return list(_alarms.values())

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

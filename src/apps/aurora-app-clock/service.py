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
import uuid
from datetime import datetime, timedelta, timezone

_BEIJING_TZ = timezone(timedelta(hours=8))
from typing import Any

from src.utils.log_utils import get_logger

logger = get_logger("aurora-app-clock.service")

# In-memory storage for alarms and timers
_alarms: dict[str, dict[str, Any]] = {}
_tasks: dict[str, asyncio.Task[None]] = {}


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
    def set_alarm(time_str: str, label: str = "") -> dict[str, Any]:
        """Store an alarm in memory and return its info with a unique id.

        Args:
            time_str: Alarm time as a string (e.g. ``"08:00"`` or ISO format).
            label:    Optional human-readable label.

        Returns:
            Dict with keys: id, time_str, label, type ("alarm").
        """
        alarm_id = uuid.uuid4().hex
        alarm: dict[str, Any] = {
            "id": alarm_id,
            "time_str": time_str,
            "label": label,
            "type": "alarm",
        }
        _alarms[alarm_id] = alarm
        logger.info("Alarm set: %s", alarm)
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
        }
        _alarms[timer_id] = timer

        async def _wait() -> None:
            try:
                await asyncio.sleep(seconds)
                logger.info("Timer expired: %s", timer)
            except asyncio.CancelledError:
                logger.info("Timer cancelled: %s", timer)
            finally:
                _alarms.pop(timer_id, None)
                _tasks.pop(timer_id, None)

        task = asyncio.create_task(_wait())
        _tasks[timer_id] = task
        logger.info("Timer set: %s", timer)
        return timer

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
            logger.warning("Alarm/timer not found: %s", alarm_id)
            return False

        task = _tasks.get(alarm_id)
        if task is not None and not task.done():
            task.cancel()

        _alarms.pop(alarm_id, None)
        _tasks.pop(alarm_id, None)
        logger.info("Alarm/timer cancelled: %s", alarm_id)
        return True

"""时钟服务 — 纯业务逻辑，无 MCP 或平台依赖。

提供时间获取、闹钟调度、定时器功能，使用内存存储。
无 MCP 或 Platform 导入。

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

# 北京时区（UTC+8）
_BEIJING_TZ = timezone(timedelta(hours=8))

from src.utils.logging import get_logger

logger = get_logger("aurora-app-clock.service")

# 闹钟和定时器的内存存储
_alarms: dict[str, dict[str, Any]] = {}
# 活跃的异步任务映射
_tasks: dict[str, asyncio.Task[None]] = {}
# MCP 通知回调（由 Platform 注入）
_notify: Callable[[str, dict[str, Any]], Awaitable[None]] | None = None
# 心跳任务标识
_HEARTBEAT_ID = "aurora-heartbeat"


def _state_path() -> Path:
    """获取持久化状态文件的路径。"""
    base = Path(os.getenv("AURORA_APP_DATA_DIR", "data/app_data")) / "org.aurora.clock"
    base.mkdir(parents=True, exist_ok=True)
    return base / "tasks.json"


def _save() -> None:
    """将当前闹钟/定时器列表原子写入持久化文件。"""
    path = _state_path()
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(list(_alarms.values()), ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


class ClockService:
    """时钟操作的核心业务逻辑。"""

    @staticmethod
    def get_current_time(fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
        """获取当前北京时间。

        Args:
            fmt: strftime 兼容的格式字符串，默认 ``"%Y-%m-%d %H:%M:%S"``。
        Returns:
            格式化后的当前时间字符串。
        """
        return datetime.now(tz=_BEIJING_TZ).strftime(fmt)

    @staticmethod
    async def initialize(notifier: Callable[[str, dict[str, Any]], Awaitable[None]] | None = None) -> None:
        """恢复持久化的待处理任务，并安装活跃的 MCP 通知发送器。"""
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
            # 过期的心跳以外任务不再恢复
            if due <= now and item.get("type") != "heartbeat":
                continue
            task_id = str(item.get("id", ""))
            if task_id:
                _alarms[task_id] = item
                ClockService._schedule(item)

    @staticmethod
    def start_heartbeat() -> dict[str, Any]:
        """恢复已有心跳或为此进程创建回退心跳。"""
        existing = _alarms.get(_HEARTBEAT_ID)
        if existing is not None:
            return existing
        interval = _heartbeat_initial_seconds()
        return ClockService._schedule_heartbeat(interval, interval)

    @staticmethod
    def sleep(seconds: int) -> dict[str, Any]:
        """将下一次自主心跳安排在指定秒数后，实际时长受心跳边界约束。"""
        if seconds <= 0:
            raise ValueError("seconds must be positive")
        fallback = _heartbeat_initial_seconds()
        existing = _alarms.get(_HEARTBEAT_ID)
        if existing is not None:
            fallback = _positive_number(existing.get("fallback_seconds"), fallback)
        # 限制在 min/max 心跳范围内
        interval = min(_heartbeat_max_seconds(), max(_heartbeat_min_seconds(), float(seconds)))
        return ClockService._schedule_heartbeat(interval, fallback)

    @staticmethod
    async def set_alarm(time_str: str, label: str = "") -> dict[str, Any]:
        """设置闹钟并存于内存中，返回包含唯一 ID 的信息。

        Args:
            time_str: 闹钟时间字符串（如 ``"08:00"`` 或 ISO 格式）。
            label:    可选的可读标签。
        Returns:
            包含 id、time_str、label、type 的字典。
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
        """创建一个等待指定秒数的定时器，触发后自动从存储中移除。

        Args:
            seconds: 等待秒数。
            label:   可选的可读标签。
        Returns:
            包含 id、seconds、label、type 的字典。
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
        """为指定条目创建异步等待任务，到期后通过 _notify 发送事件。"""
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
                        # 心跳触发后自动调度下一个心跳
                        fallback = _positive_number(item.get("fallback_seconds"), _heartbeat_initial_seconds())
                        ClockService._schedule_heartbeat(fallback, fallback)
                    else:
                        _save()

        _tasks[task_id] = asyncio.create_task(_wait())

    @staticmethod
    def list_alarms() -> list[dict[str, Any]]:
        """列出所有已调度的闹钟和定时器（不含心跳）。

        Returns:
            当前内存中存储的闹钟/定时器字典列表。
        """
        return [item for item in _alarms.values() if item.get("type") != "heartbeat"]

    @staticmethod
    def cancel_alarm(alarm_id: str) -> bool:
        """按 ID 取消闹钟或定时器。

        Args:
            alarm_id: ``set_alarm`` 或 ``set_timer`` 返回的唯一标识。
        Returns:
            找到并取消成功返回 ``True``，否则 ``False``。
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
        """安排心跳任务，替换已有的活跃心跳。"""
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
    """解析闹钟时间字符串为 UTC datetime。

    支持 ISO-8601 格式和 HH:MM 格式；
    HH:MM 格式取当天对应时间，若已过则顺延至次日。
    """
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
    """安全地将值转换为正数，失败或非正时返回默认值。"""
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
    """从环境变量读取心跳初始间隔，默认 30 秒。"""
    return _positive_number(os.getenv("AURORA_CLOCK_HEARTBEAT_INITIAL_SECONDS"), 30.0)


def _heartbeat_min_seconds() -> float:
    """从环境变量读取心跳最小间隔，默认 30 秒。"""
    return _positive_number(os.getenv("AURORA_CLOCK_HEARTBEAT_MIN_SECONDS"), 30.0)


def _heartbeat_max_seconds() -> float:
    """从环境变量读取心跳最大间隔，默认 1800 秒，且不小于最小间隔。"""
    return max(
        _heartbeat_min_seconds(),
        _positive_number(os.getenv("AURORA_CLOCK_HEARTBEAT_MAX_SECONDS"), 1800.0),
    )

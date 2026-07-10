"""TimerScheduler — 心跳 → 节律事件触发器。

纯机械 Router 节点。watch heartbeat/tick.json，
根据配置中的时间规则，在匹配时产出 rhythm/triggers/{name}.json。
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any

from src.kernel.base import FileDescriptor, FileUpdate, Router
from src.utils.log_utils import get_logger

logger = get_logger("TimerScheduler")

DEFAULT_RULES: list[dict[str, Any]] = [
    {"name": "hourly", "minute": 0, "emit": "rhythm/triggers/hourly.json"},
    {"name": "morning", "minute": 0, "hour": 8, "emit": "rhythm/triggers/morning.json"},
    {"name": "evening", "minute": 0, "hour": 22, "emit": "rhythm/triggers/evening.json"},
    {"name": "midnight", "minute": 0, "hour": 2, "emit": "rhythm/triggers/midnight.json"},
]


class TimerScheduler(Router):
    """节律调度器。"""

    _default_guards = ["heartbeat/tick.json"]
    _default_produces = ["rhythm/triggers/*.json"]

    def __init__(self, node_id: str, *, rules: list[dict[str, Any]] | None = None, **kwargs: Any) -> None:
        super().__init__(node_id, **kwargs)
        self._rules = rules or DEFAULT_RULES
        self._last_trigger: dict[str, str] = {}

    async def execute(self) -> list[FileUpdate]:
        now = datetime.now()
        current_minute = now.minute
        current_hour = now.hour
        date_hour = now.strftime("%Y-%m-%d %H")

        updates: list[FileUpdate] = []

        for rule in self._rules:
            name = str(rule.get("name", "unnamed"))
            emit_path = str(rule.get("emit", ""))
            if not emit_path:
                continue

            rule_minute = rule.get("minute")
            rule_hour = rule.get("hour")
            minute_match = rule_minute is None or rule_minute == "*" or int(rule_minute) == current_minute
            hour_match = rule_hour is None or rule_hour == "*" or int(rule_hour) == current_hour
            if not (minute_match and hour_match):
                continue

            trigger_key = f"{name}:{date_hour}"
            if self._last_trigger.get(name) == trigger_key:
                continue
            self._last_trigger[name] = trigger_key

            trigger_data = {
                "name": name,
                "timestamp": time.time(),
                "datetime": now.isoformat(),
                "emit_path": emit_path,
            }

            update = FileUpdate(
                descriptor=FileDescriptor(path=emit_path, schema="json"),
                content=trigger_data,
            )
            updates.append(update)
            logger.info("节律触发: %s → %s", name, emit_path)

        return updates

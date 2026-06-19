"""TimerScheduler —— 心跳 → 节律事件触发器。

纯机械 Router 节点。watch ``heartbeat/tick.json``，
根据配置中的时间规则，在匹配时产出 ``rhythm/triggers/{name}.json``。

每个规则追踪上次触发时间，同一周期内不重复触发。
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any

from src.brain.kernel.base import FileDescriptor, FileUpdate, Router
from src.utils.log_utils import get_logger

logger = get_logger("TimerScheduler")

# 默认调度规则
DEFAULT_RULES: list[dict[str, Any]] = [
    {"name": "hourly", "minute": 0, "emit": "rhythm/triggers/hourly.json"},
    {"name": "morning", "minute": 0, "hour": 8, "emit": "rhythm/triggers/morning.json"},
    {"name": "evening", "minute": 0, "hour": 22, "emit": "rhythm/triggers/evening.json"},
    {"name": "midnight", "minute": 0, "hour": 2, "emit": "rhythm/triggers/midnight.json"},
]


class TimerScheduler(Router):
    """节律调度器。

    watch ``heartbeat/tick.json``，根据 config.rules 中的时间规则，
    在当前时间匹配时写入 ``rhythm/triggers/{name}.json``。
    每个规则在匹配的时间窗口内只触发一次（按 (name, date, hour) 去重）。

    config.rules 格式::

        rules:
          - name: hourly
            minute: 0          # 每小时整点
            emit: "rhythm/triggers/hourly.json"
          - name: morning
            minute: 0
            hour: 8            # 每天 8:00
            emit: "rhythm/triggers/morning.json"
    """

    _default_guards = ["heartbeat/tick.json"]  # noqa: RUF012
    _default_produces = ["rhythm/triggers/*.json"]  # noqa: RUF012

    def __init__(
        self,
        node_id: str,
        host: "object | None" = None,
        *,
        rules: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(node_id, host=host, **kwargs)
        self._rules = rules or DEFAULT_RULES
        self._last_trigger: dict[str, str] = {}  # name → "YYYY-MM-DD HH"

    async def execute(self) -> list[FileUpdate]:
        now = datetime.now()  # noqa: DTZ005
        current_minute = now.minute
        current_hour = now.hour
        date_hour = now.strftime("%Y-%m-%d %H")

        updates: list[FileUpdate] = []

        for rule in self._rules:
            name = str(rule.get("name", "unnamed"))
            emit_path = str(rule.get("emit", ""))

            if not emit_path:
                continue

            # 检查时间匹配
            rule_minute = rule.get("minute")
            rule_hour = rule.get("hour")

            minute_match = rule_minute is None or rule_minute == "*" or int(rule_minute) == current_minute
            hour_match = rule_hour is None or rule_hour == "*" or int(rule_hour) == current_hour

            if not (minute_match and hour_match):
                continue

            # 去重：相同 (name, date_hour) 不重复触发
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

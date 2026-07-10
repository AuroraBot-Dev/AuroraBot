"""HeartbeatGenerator — 周期性心跳脉冲发生器。

纯机械 Router 节点。通过 watch 自身 emit 的文件实现自持振荡。
每次被自己的 tick 唤醒后，sleep N 秒再写入下一个 tick，
tick 落盘生成 FileEvent → 再次唤醒自己 → 形成永久循环。
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from src.config import Config
from src.kernel.base import FileDescriptor, FileEvent, FileUpdate, NodeState, Router
from src.utils.log_utils import get_logger

logger = get_logger("Heartbeat")


class HeartbeatGenerator(Router):
    """周期性心跳发生器。

    watch + emit 同一路径 heartbeat/tick.json，形成自持振荡回路。
    """

    _default_guards = ["heartbeat/tick.json"]
    _default_produces = ["heartbeat/tick.json"]

    def __init__(self, node_id: str, *, interval_sec: float = 60.0, **kwargs: Any) -> None:
        super().__init__(node_id, **kwargs)
        self._interval = max(1.0, float(interval_sec))
        self._tick_count = 0

    def on_event(self, event: FileEvent) -> bool:
        """覆写基类方法 — 允许自身产出的事件唤醒自己（自持振荡）。"""
        if self.state not in (NodeState.IDLE, NodeState.READY):
            return False
        return any(guard.match(event.path) for guard in self.guards)

    async def execute(self) -> list[FileUpdate]:
        await asyncio.sleep(self._interval)

        self._tick_count += 1
        tick_id = f"tick_{self._tick_count:06d}"

        tick_data = {
            "tick_id": tick_id,
            "tick_number": self._tick_count,
            "timestamp": time.time(),
            "interval_sec": self._interval,
        }

        heartbeat_dir = Config.KERNEL_DATA_DIR / "heartbeat"
        heartbeat_dir.mkdir(parents=True, exist_ok=True)
        tick_path = heartbeat_dir / "tick.json"
        tick_path.write_text(
            json.dumps(tick_data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        update = FileUpdate(
            descriptor=FileDescriptor(path="heartbeat/tick.json", schema="json"),
            content=tick_data,
        )

        logger.debug("心跳 #%d (%.0fs 间隔)", self._tick_count, self._interval)
        return [update]

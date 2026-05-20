from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

from src.brain.kernel.base import (
    FileDescriptor,
    FileEvent,
    FilePattern,
    FileUpdate,
    NodeState,
    Router,
)
from src.config import Config
from src.utils.log_utils import get_logger

logger = get_logger("HeartbeatRouter")

_DATA_DIR = Config.KERNEL_DATA_DIR


class HeartbeatRouter(Router):
    """定时脉冲 Router —— 自触发循环，周期性产生 heartbeat 事件。

    纯机械逻辑，零 LLM 调用。

    守护 ``heartbeat/tick.json`` 文件。覆写 ``on_event`` 允许
    自身产出的事件触发自身，形成自持振荡。每次执行检查上次
    写入时间戳，间隔未到则返回空（不自旋——靠文件事件唤醒）。

    参数在构造时通过 ``**config`` 传入：
    - ``interval_sec``: 脉冲间隔（秒），默认 300（5 分钟）
    """

    def __init__(self, node_id: str, **config: Any) -> None:
        super().__init__(node_id)
        self._interval_sec = float(config.get("interval_sec", 300))
        self._tick_dir = _DATA_DIR / "heartbeat"

    @property
    def type(self) -> str:
        return "router"

    @property
    def guards(self) -> list[FilePattern]:
        if self._config_watch is not None:
            return [FilePattern(p) for p in self._config_watch]
        return [FilePattern("heartbeat/tick.json")]

    @property
    def produces(self) -> list[FileDescriptor]:
        if self._config_emit is not None:
            return [FileDescriptor(p) for p in self._config_emit]
        return [FileDescriptor("heartbeat/tick.json")]

    def on_event(self, event: FileEvent) -> bool:
        """允许自触发 —— 心跳的本质是自我维持的振荡。"""
        if self.state not in (NodeState.IDLE, NodeState.READY):
            return False
        return any(g.match(event.path) for g in self.guards)

    async def execute(self) -> list[FileUpdate]:
        tick_path = self._tick_dir / "tick.json"
        now = time.time()

        if tick_path.exists():
            try:
                data = json.loads(tick_path.read_text(encoding="utf-8"))
                last_tick = float(data.get("timestamp", 0))
                if now - last_tick < self._interval_sec:
                    return []  # 时间未到，不产出
            except (OSError, json.JSONDecodeError, ValueError):
                pass  # 文件损坏 → 重新生成

        self._tick_dir.mkdir(parents=True, exist_ok=True)

        tick_data = {
            "tick_id": uuid.uuid4().hex[:12],
            "timestamp": now,
            "interval_sec": self._interval_sec,
        }
        logger.debug(f"Heartbeat: tick {tick_data['tick_id']}")

        return [
            FileUpdate(
                descriptor=FileDescriptor(
                    path="heartbeat/tick.json",
                    schema="json",
                ),
                content=tick_data,
            )
        ]

    def on_complete(self) -> None:
        if self.state != NodeState.ERROR:
            self.state = NodeState.IDLE

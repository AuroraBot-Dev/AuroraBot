"""HeartbeatGenerator —— 周期性心跳脉冲发生器。

纯机械 Router 节点。不同于 Circuit._bootstrap_heartbeat() 的一次性引导，
这是一个**持续运行的独立节点**——通过 watch 自身 emit 的文件实现自持振荡。

每次被自己的 tick 唤醒后，sleep N 秒再写入下一个 tick，
tick 落盘生成 FileEvent → 再次唤醒自己 → 形成永久循环。

同时，tick 事件也触发所有其他 watch heartbeat/tick.json 的节点
（如 TimerScheduler），驱动整个节律系统。
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import TYPE_CHECKING, Any

from src.brain.kernel.base import FileDescriptor, FileEvent, FileUpdate, NodeState, Router
from src.config import Config
from src.utils.log_utils import get_logger

if TYPE_CHECKING:
    from src.platform.application_host import ApplicationHost

logger = get_logger("Heartbeat")


class HeartbeatGenerator(Router):
    """周期性心跳发生器。

    watch + emit 同一路径 ``heartbeat/tick.json``，形成自持振荡回路。
    Circuit 的 _bootstrap_heartbeat() 写入第一个 tick 后，
    本节点接管后续所有 tick 的生成。

    可配置 interval_sec（默认 60s）。
    """

    _default_guards = ["heartbeat/tick.json"]  # noqa: RUF012
    _default_produces = ["heartbeat/tick.json"]  # noqa: RUF012

    def __init__(
        self,
        node_id: str,
        host: "ApplicationHost | None" = None,
        *,
        interval_sec: float = 60.0,
        **kwargs: Any,
    ) -> None:
        super().__init__(node_id, host=host, **kwargs)
        self._interval = max(1.0, float(interval_sec))
        self._tick_count = 0

    # ── 允许自触发 ──────────────────────────────────

    def on_event(self, event: FileEvent) -> bool:
        """覆写基类方法——允许自身产出的事件唤醒自己。

        标准 Node.on_event() 会跳过 source_node == self.id 的事件，
        但心跳节点依赖自持振荡，必须接收自己写入的 tick 事件。
        """
        if self.state not in (NodeState.IDLE, NodeState.READY):
            return False
        return any(guard.match(event.path) for guard in self.guards)

    # ── 执行 ────────────────────────────────────────

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

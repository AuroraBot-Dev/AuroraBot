from __future__ import annotations

import asyncio
import contextlib
from typing import TYPE_CHECKING

from src.brain.kernel.base import FileDescriptor, FileUpdate
from src.utils.log_utils import get_logger

if TYPE_CHECKING:
    from src.brain.kernel.circuit import Circuit
    from src.platform.application_host import ApplicationHost

logger = get_logger("EventBridge")

_DEFAULT_INTERVAL = 0.5


async def run_event_bridge(
    host: ApplicationHost,
    circuit: Circuit,
    stop_event: asyncio.Event,
    interval: float = _DEFAULT_INTERVAL,
) -> None:
    """将 ApplicationHost 的 AppEvent 桥接到 Circuit 的文件事件。

    App 层通过 ``host.emit_event(AppEvent)`` 上报事件，
    而 Node 图结构通过文件变更（FileEvent）驱动。

    本桥接层是两者的正式接口：
    1. 定期 drain ApplicationHost 事件队列
    2. 每个事件写入 ``data/kernel/inbox/event_<type>_<id>.json``
    3. 写入自动触发 FileEvent，唤醒下游节点

    Parameters
    ----------
    host : ApplicationHost
        应用宿主，从中 drain AppEvent。
    circuit : Circuit
        Node 图结构电路，通过 ``apply_update`` 注入文件变更。
    stop_event : asyncio.Event
        停止信号，置位时退出循环。
    interval : float
        轮询间隔（秒），默认 0.5。
    """
    logger.info("事件桥接已启动")
    while not stop_event.is_set():
        try:
            events = host.drain_events()
            if events:
                logger.debug(f"桥接 {len(events)} 个事件到文件总线")
                for event in events:
                    # 文件名编码事件类型，允许节点按类型精细化订阅
                    safe_type = str(event.type).replace(".", "_").replace("/", "_")
                    file_path = f"inbox/event_{safe_type}_{event.id}.json"
                    update = FileUpdate(
                        descriptor=FileDescriptor(
                            path=file_path,
                            schema="json",
                        ),
                        content=event.to_dict(),
                    )
                    await circuit.apply_update(update, node_id="event_bridge")
        except Exception:  # noqa: BLE001
            logger.exception("事件桥接异常")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=max(0.05, interval))
        except asyncio.TimeoutError:
            continue

    logger.info("事件桥接已停止")

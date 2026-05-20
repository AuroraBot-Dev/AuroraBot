from __future__ import annotations

import asyncio
import json
import time
from typing import TYPE_CHECKING

from src.brain.kernel.base import FileEvent, FileUpdate, NodeState
from src.brain.kernel.event_bus import FileEventBus
from src.config import Config
from src.utils.log_utils import get_logger

if TYPE_CHECKING:
    from src.brain.kernel.base import FileEvent, Node

logger = get_logger("Circuit")


class Circuit:
    """认知拓扑电路编排器。

    管理一个 :class:`FileEventBus` 和一组 :class:`Node` 实例的
    协程生命周期。每个节点运行独立的 ``run()`` 协程，文件事件
    通过总线在有环图中流转。

    Parameters
    ----------
    nodes : list[Node]
        组成电路的所有节点。启动前需已完成子类实例化。
    """

    def __init__(self, nodes: list[Node]) -> None:
        self._nodes = nodes
        self._bus: FileEventBus | None = None
        self._node_tasks: list[asyncio.Task[None]] = []

    @property
    def is_running(self) -> bool:
        return self._bus is not None

    async def start(self) -> None:
        """启动电路。

        创建事件总线并将其注入所有节点，然后并行启动分发循环
        和每个节点的 ``run()`` 协程。
        """
        if self._bus is not None:
            logger.warning("电路已在运行中，忽略重复启动")
            return

        self._bus = FileEventBus(self._nodes)

        for node in self._nodes:
            node._bus = self._bus

        dispatch_task = asyncio.create_task(self._bus.dispatch_forever())
        self._bus._dispatch_task = dispatch_task

        # Bootstrap: 创建初始 heartbeat 文件，触发自持振荡回路
        self._bootstrap_heartbeat()

        for node in self._nodes:
            task = asyncio.create_task(node.run())
            self._node_tasks.append(task)

        logger.info(
            f"电路已启动: {len(self._nodes)} 个节点, "
            f"{', '.join(node.name for node in self._nodes)}"
        )

    async def stop(self) -> None:
        """停止电路。

        置位所有节点的终止标志并唤醒等待中的协程，
        逐一取消分发任务和节点任务。
        """
        if self._bus is None:
            return

        for node in self._nodes:
            node.state = NodeState.TERMINATED
            node._ready_event.set()

        await self._bus.shutdown()

        for task in self._node_tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*self._node_tasks, return_exceptions=True)

        self._node_tasks.clear()
        self._bus = None

        logger.info("电路已停止")

    def inject_event(self, event: FileEvent) -> None:
        """向电路注入一个外部文件事件。

        调用后，事件进入总线队列，匹配的节点将被激活并开始执行。
        这是电路的外部入口之一。

        Parameters
        ----------
        event : FileEvent
            要注入的外部事件。
        """
        if self._bus is None:
            raise RuntimeError("电路未启动，无法注入事件")
        self._bus.publish(event)

    def _bootstrap_heartbeat(self) -> None:
        """创建初始 heartbeat/tick.json 并注入事件，启动自持振荡回路。"""
        heartbeat_dir = Config.KERNEL_DATA_DIR / "heartbeat"
        heartbeat_dir.mkdir(parents=True, exist_ok=True)
        tick_path = heartbeat_dir / "tick.json"

        tick_data = {
            "tick_id": "bootstrap",
            "timestamp": time.time(),
            "interval_sec": 300,
        }
        tick_path.write_text(
            json.dumps(tick_data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        if self._bus is not None:
            self._bus.publish(
                FileEvent(
                    path="heartbeat/tick.json",
                    change_type="write",
                    metadata={"source_node": "circuit_bootstrap"},
                )
            )
        logger.info("Heartbeat 初始脉冲已注入")

    async def apply_update(self, update: FileUpdate, node_id: str = "system") -> None:
        """向电路写入一个文件变更并触发下游事件。

        将 :class:`FileUpdate` 通过总线落盘，落盘后自动生成
        ``change_type="write"`` 的 :class:`FileEvent` 并重新注入总线，
        匹配的节点将被激活。

        这是迁移期事件桥接的主要入口——外部系统（如 ApplicationHost）
        通过此方法将事件转化为文件，驱动节点图中的下游节点。

        Parameters
        ----------
        update : FileUpdate
            要落盘的文件变更。
        node_id : str
            触发写入的节点标识，默认 ``"system"``。
        """
        if self._bus is None:
            raise RuntimeError("电路未启动，无法写入文件")
        await self._bus.apply_update(update, node_id)

    async def __aenter__(self) -> Circuit:
        await self.start()
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.stop()

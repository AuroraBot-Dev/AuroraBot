from __future__ import annotations

import asyncio
import contextlib
import json
from typing import TYPE_CHECKING, Any

from src.config import Config
from src.kernel.base import FileEvent, FileUpdate
from src.utils.log_utils import get_logger

if TYPE_CHECKING:
    from pathlib import Path

    from src.kernel.base import Node

logger = get_logger("FileEventBus")


class FileEventBus:
    """认知拓扑电路的文件事件总线。

    职责:
    - 接收 :class:`FileEvent` 并通过守护匹配调度到各 Node
    - 为 :class:`FileUpdate` 提供带锁写入，尊重文件描述符中的锁策略
    - 文件落盘后自动生成下游 :class:`FileEvent` 并重新注入总线

    Parameters
    ----------
    nodes : list[Node]
        电路中的所有节点。
    data_dir : Path, optional
        文件落盘的根目录，默认使用 ``Config.KERNEL_DATA_DIR``。
    """

    def __init__(
        self,
        nodes: list[Node],
        data_dir: Path | None = None,
    ) -> None:
        self._nodes = nodes
        self._data_dir = data_dir or Config.KERNEL_DATA_DIR
        self._queue: asyncio.Queue[FileEvent] = asyncio.Queue()
        self._file_locks: dict[str, asyncio.Lock] = {}
        self._dispatch_task: asyncio.Task[None] | None = None

    def publish(self, event: FileEvent) -> None:
        """发布文件事件到总线。"""
        self._queue.put_nowait(event)

    async def apply_update(self, update: FileUpdate, node_id: str) -> None:
        """写入文件更新并发布下游事件。

        根据文件描述符中的锁策略取文件级 ``asyncio.Lock``，
        写入文件后生成 ``change_type="write"`` 的 :class:`FileEvent`
        并注入总线。

        Parameters
        ----------
        update : FileUpdate
            要落盘的文件变更。
        node_id : str
            触发写入的节点 ID。
        """
        descriptor = update.descriptor
        file_path = self._data_dir / descriptor.path
        lock = self._get_lock(descriptor.path)

        async with lock:
            self._write_file(file_path, descriptor.schema, update.content, update.mode)

        event = FileEvent(
            path=descriptor.path,
            change_type="write",
            metadata={
                "source_node": node_id,
                "lock": descriptor.lock,
            },
        )
        self.publish(event)

    async def dispatch_forever(self) -> None:
        """事件分发主循环。

        由 :class:`Circuit` 启动为 ``asyncio.Task``。
        持续从队列中取出 :class:`FileEvent`，遍历所有节点调用
        :meth:`Node.on_event`，命中的节点标记 ``READY`` 并唤醒。
        """
        while True:
            try:
                event = await self._queue.get()
            except asyncio.CancelledError:
                return

            try:
                self._dispatch_to_nodes(event)
            except Exception:
                logger.exception(f"事件分发异常: path={event.path}")

    def start_dispatch(self) -> None:
        """启动事件分发循环（创建 asyncio.Task）。

        调用后 :attr:`_dispatch_task` 持有分发循环的引用，
        可通过 :meth:`shutdown` 停止。
        """
        self._dispatch_task = asyncio.create_task(self.dispatch_forever())

    async def shutdown(self) -> None:
        """停止分发循环。"""
        if self._dispatch_task is not None and not self._dispatch_task.done():
            self._dispatch_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._dispatch_task
            self._dispatch_task = None

    def _get_lock(self, path_key: str) -> asyncio.Lock:
        if path_key not in self._file_locks:
            self._file_locks[path_key] = asyncio.Lock()
        return self._file_locks[path_key]

    def _dispatch_to_nodes(self, event: FileEvent) -> None:
        hit_any = False
        for node in self._nodes:
            try:
                if node.on_event(event):
                    node.wake()
                    hit_any = True
            except Exception:
                logger.exception(f"节点 {node.name}({node.id}) on_event 异常: path={event.path}")
        if not hit_any:
            logger.debug(f"无节点匹配事件: path={event.path}, change_type={event.change_type}")

    def _write_file(
        self,
        file_path: Path,
        schema: str,
        content: Any,
        mode: str,
    ) -> None:
        file_path.parent.mkdir(parents=True, exist_ok=True)

        if schema == "json":
            self._write_json_file(file_path, content, mode)
        else:
            self._write_text_file(file_path, content, mode)

    def _write_json_file(self, path: Path, content: Any, mode: str) -> None:
        if mode == "append":
            existing: Any = []
            if path.exists():
                try:
                    existing = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    existing = []
            if not isinstance(existing, list):
                existing = [existing]
            if isinstance(content, list):
                existing.extend(content)
            else:
                existing.append(content)
            path.write_text(
                json.dumps(existing, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        else:
            path.write_text(
                json.dumps(content, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )

    def _write_text_file(self, path: Path, content: Any, mode: str) -> None:
        text = str(content)
        if mode == "append" and path.exists():
            text = path.read_text(encoding="utf-8") + text
        path.write_text(text, encoding="utf-8")

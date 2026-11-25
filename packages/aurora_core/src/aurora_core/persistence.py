"""完整 ctx 快照的异步自动写入与显式收尾。"""

import asyncio
import logging
import math
from collections.abc import Callable
from functools import partial

from .ctx import Context
from .snapshots import JsonSnapshotStore

logger = logging.getLogger(__name__)


async def _finish_io[T](operation: Callable[[], T]) -> T:
    """取消调用时也等待线程 I/O 结束，防止旧写入在后续写入之后覆盖文件。"""
    task = asyncio.create_task(asyncio.to_thread(operation))
    cancelled = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled = True
    result = task.result()
    if cancelled:
        raise asyncio.CancelledError
    return result


class ContextPersistence:
    """在一个宿主事件循环内管理快照，默认每 0.5 秒合并一次状态变化。

    start 先恢复再启动自动写入；flush 等待当时及写入期间产生的变更落盘。
    close 停止自动任务并完成最后写入，成功后才释放订阅；失败保留重试能力。
    宿主须先结束写入来源，再 close 本对象，最后关闭 ctx。
    """

    def __init__(self, ctx: Context, store: JsonSnapshotStore, *, interval: float = 0.5) -> None:
        if not math.isfinite(interval) or interval <= 0:
            raise ValueError("自动落盘间隔必须为正有限数")
        self._ctx = ctx
        self._store = store
        self._interval = interval
        self._loop: asyncio.AbstractEventLoop | None = None
        self._starting = False
        self._closed = False
        self._saved_revision = -1
        self._handle: str | None = None
        self._worker: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()
        self._changed = asyncio.Event()
        self._lock = asyncio.Lock()
        self._close_lock = asyncio.Lock()
        self.last_error: Exception | None = None

    async def start(self) -> None:
        """在尚未写入的 ctx 上恢复；读取或校验失败不启动自动任务。"""
        if self._starting or self._loop is not None or self._closed:
            raise RuntimeError("持久化已启动或正在启动")
        self._starting = True
        try:
            # 先验证宿主线程及 ctx 是否可用，再交给后台线程读取文件。
            self._ctx.snapshot()
            records = await _finish_io(self._store.load)
            self._ctx.restore(records)
            self._handle = self._ctx.subscribe(lambda change: self._changed.set())
            self._loop = asyncio.get_running_loop()
            self._saved_revision = 0
            self._worker = asyncio.create_task(self._run(), name="aurora-ctx-persistence")
        finally:
            self._starting = False

    def _check_loop(self) -> None:
        if self._loop is None:
            raise RuntimeError("持久化尚未启动")
        if asyncio.get_running_loop() is not self._loop:
            raise RuntimeError("持久化接口必须在启动它的宿主事件循环调用")

    async def flush(self) -> None:
        """串行保存完整快照；失败明确抛出并保留待写入修订。"""
        self._check_loop()
        if self._closed:
            raise RuntimeError("持久化已关闭")
        async with self._lock:
            if self._closed:
                raise RuntimeError("持久化已关闭")
            try:
                while True:
                    snapshot = self._ctx.snapshot(persistent_only=True)
                    if snapshot.revision == self._saved_revision:
                        self.last_error = None
                        return
                    await _finish_io(partial(self._store.save, snapshot))
                    self._saved_revision = snapshot.revision
            except Exception as error:
                self.last_error = error
                raise

    async def _run(self) -> None:
        while not self._stop.is_set():
            await self._changed.wait()
            self._changed.clear()
            if self._stop.is_set():
                break
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._interval)
                break
            except TimeoutError:
                pass
            try:
                await self.flush()
            except Exception:
                logger.exception("ctx 自动落盘失败；保留待写入状态并等待重试")
                self._changed.set()

    async def close(self) -> None:
        """成功落盘后结束订阅；失败可再次调用 close，不关闭 ctx 本身。"""
        self._check_loop()
        async with self._close_lock:
            if self._closed:
                return
            self._stop.set()
            self._changed.set()
            if self._worker is not None:
                await asyncio.shield(self._worker)
            await self.flush()
            if self._handle is not None:
                self._ctx.unsubscribe(self._handle)
                self._handle = None
            self._closed = True

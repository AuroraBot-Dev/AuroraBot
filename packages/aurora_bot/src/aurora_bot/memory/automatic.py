"""压缩材料同步落盘，摘要索引由宿主持有的可恢复队列异步处理。"""

import asyncio
import logging
from collections.abc import Awaitable, Callable

from aurora_adapter.model import EmbeddingClient
from aurora_adapter.model.usage import usage_scope
from aurora_agent.compaction import CompactionRecord

from .store import MemoryStore

logger = logging.getLogger(__name__)


class CompactionMemory:
    """数据库提交先于上下文替换；供应商失败只延后索引，不丢弃已归档材料。"""

    def __init__(
        self,
        store: MemoryStore,
        client_factory: Callable[[], Awaitable[EmbeddingClient]],
        *,
        index_timeout_seconds: float,
        retry_seconds: float,
    ):
        self.store, self.client_factory = store, client_factory
        self.index_timeout_seconds, self.retry_seconds = index_timeout_seconds, retry_seconds
        self._wake = asyncio.Event()
        self._task: asyncio.Task | None = None

    def archive(self, record: CompactionRecord) -> None:
        self.store.archive(record)

    def remember(self, digest: str, text: str) -> None:
        self.store.queue_summary(digest, text)
        self._wake.set()

    def start(self) -> None:
        if self._task is None:
            self._wake.set()
            self._task = asyncio.create_task(self._run(), name="compaction-memory")

    async def _run(self) -> None:
        while True:
            try:
                await asyncio.wait_for(self._wake.wait(), self.retry_seconds)
            except TimeoutError:
                pass
            self._wake.clear()
            try:
                jobs = self.store.pending_compactions()
                failed = False
                for job in jobs:
                    try:
                        async with asyncio.timeout(self.index_timeout_seconds):
                            if self.store.client is None:
                                self.store.client = await self.client_factory()
                            with usage_scope("memory_compaction"):
                                await self.store.index_compaction(job)
                    except Exception as error:  # noqa: BLE001 — 后台索引失败保留队列，日志仅输出脱敏类型。
                        failed = True
                        self.store.defer_compaction(job["digest"])
                        logger.warning("自动记忆索引延后，原文和摘要已落盘：%s", type(error).__name__)
                if len(jobs) == 16 and not failed:
                    self._wake.set()
            except Exception as error:  # noqa: BLE001 — 数据库故障保留待处理记录，下一周期重试。
                logger.error("自动记忆队列读取或提交失败：%s", type(error).__name__)

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def close(self) -> None:
        await self.stop()
        if self.store.client is not None:
            await self.store.client.aclose()
            self.store.client = None
        self.store.close()

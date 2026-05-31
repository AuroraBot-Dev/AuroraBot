"""DeadLetterRouter —— 超期文件回收。

纯机械 Router 节点。定期扫描 kernel_data_dir 下的所有 done/ 目录和
pipeline 中间目录，将超过 config.ttl_sec 未被消费的文件移动到
``dead_letter/`` 目录。

防止孤儿文件无限堆积。
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
from typing import TYPE_CHECKING, Any

from src.brain.kernel.base import FileDescriptor, FileUpdate, Router
from src.brain.kernel.state_store import kernel_data_dir, next_record_id
from src.utils.log_utils import get_logger

if TYPE_CHECKING:
    from pathlib import Path

    from src.platform.application_host import ApplicationHost

logger = get_logger("DeadLetter")


class DeadLetterRouter(Router):
    """超期文件回收器。

    自定时节点——不 watch 外部文件，通过 execute() 内部 sleep 周期性扫描。
    config::

        ttl_sec: 3600        # 文件存活时间（秒），默认 1 小时
        scan_interval: 600   # 扫描间隔（秒），默认 10 分钟
    """

    _default_guards: list[str] = []  # noqa: RUF012 — 自定时，不依赖事件
    _default_produces = ["dead_letter/*.json"]  # noqa: RUF012

    def __init__(
        self,
        node_id: str,
        host: "ApplicationHost | None" = None,
        *,
        ttl_sec: float = 3600.0,
        scan_interval: float = 600.0,
        **kwargs: Any,
    ) -> None:
        super().__init__(node_id, host=host, **kwargs)
        self._ttl_sec = max(60.0, float(ttl_sec))
        self._scan_interval = max(30.0, float(scan_interval))

    # ── 自定时循环 ──────────────────────────────────

    async def run(self) -> None:
        """覆写 Node.run()——自定时扫描，不依赖 _ready_event。"""
        from src.brain.kernel.base import NodeState

        while self.state != NodeState.TERMINATED:
            await asyncio.sleep(self._scan_interval)
            self.state = NodeState.RUNNING
            try:
                updates = await self.execute()
            except asyncio.CancelledError:
                return
            except Exception:
                logger.exception("DeadLetterRouter 扫描异常")
                self.state = NodeState.ERROR
                continue

            if self._bus is not None:
                for update in updates:
                    try:
                        await self._bus.apply_update(update, self.id)
                    except Exception:
                        logger.exception("写入 dead_letter 异常: %s", update.descriptor.path)

            self.state = NodeState.IDLE

    # ── 执行 ────────────────────────────────────────

    async def execute(self) -> list[FileUpdate]:
        now = time.time()
        updates: list[FileUpdate] = []
        scanned = 0

        for file_path in self._scan_targets():
            scanned += 1
            try:
                mtime = file_path.stat().st_mtime
            except OSError:
                continue

            age = now - mtime
            if age < self._ttl_sec:
                continue

            # 读取内容，移动到 dead_letter
            try:
                data = json.loads(file_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                data = {"_unreadable": True}

            dl_id = next_record_id("dl")
            # 保留原始路径结构
            rel = str(file_path.relative_to(kernel_data_dir)).replace("/", "_").replace("\\", "_")
            dl_path = f"dead_letter/{rel}_{dl_id}.json"

            update = FileUpdate(
                descriptor=FileDescriptor(path=dl_path, schema="json"),
                content={"original_path": str(file_path), "age_sec": age, "data": data},
            )
            updates.append(update)

            # 删除源文件
            with contextlib.suppress(OSError):
                file_path.unlink()

        if updates:
            logger.info("回收 %d 个超期文件 (扫描 %d 个)", len(updates), scanned)
        return updates

    def _scan_targets(self) -> list["Path"]:
        """扫描所有可能产生孤儿文件的目录。"""
        targets: list[Path] = []
        scan_roots = [
            kernel_data_dir / "pipeline",
            kernel_data_dir / "inbox" / "pending",
            kernel_data_dir / "reflection" / "inbox",
            kernel_data_dir / "rhythm" / "triggers",
        ]
        for root in scan_roots:
            if not root.exists():
                continue
            # 只扫描 JSON 文件，跳过 done/ 子目录
            for path in root.rglob("*.json"):
                if "done" in path.parts:
                    continue
                targets.append(path)
        return targets

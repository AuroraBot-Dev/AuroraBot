"""MemoryProjector — 终态 Task 的长期记忆投影贡献。

接收 engine 从已提交 Task/Agent 事实中提取的 MemoryEntry 投影，写入同一
MemoryService。单条失败只记日志并继续，不阻断其他终态投影。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.contracts import MemoryEntry
from src.utils import get_logger

if TYPE_CHECKING:
    from src.memory.service import MemoryService

logger = get_logger("aurora.memory.projector")


class MemoryProjector:
    """把终态记忆事实写入 durable facts 与语义长期记忆。"""

    def __init__(self, memory: "MemoryService") -> None:
        self._memory = memory

    async def project(self, facts: tuple[dict[str, Any], ...]) -> None:
        for raw in facts:
            entry = MemoryEntry.from_dict(raw)
            try:
                await self._memory.remember(entry)
            except Exception as error:  # noqa: BLE001 - 单条投影失败不得阻断后续事实
                logger.warning(
                    "Memory projector remember failed task_id=%s error_type=%s",
                    entry.task_id,
                    type(error).__name__,
                )

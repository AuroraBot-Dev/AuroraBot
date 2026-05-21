from __future__ import annotations
import json
from pathlib import Path
from typing import Any

from src.brain.kernel.base import FileUpdate, Router
from src.brain.kernel.state_store import kernel_data_dir, move_to_done
from src.utils.log_utils import get_logger

logger = get_logger("MemoryRouter")


class MemoryRouter(Router):
    """记忆记录 Router —— 将事件写入 L1/L2/L3 三级记忆系统。

    纯机械逻辑，零 LLM 调用。

    守护 ``memory/pending/event_*.json``，通过
    :class:`UnifiedMemoryManager.process_interaction` 将事件
    瀑布式写入工作记忆(L1)、情景记忆(L2)、语义记忆(L3)。

    处理完成的输入文件移入 ``done/`` 子目录。
    """

    def __init__(self, node_id: str, **config: Any) -> None:
        super().__init__(node_id)

    async def execute(self) -> list[FileUpdate]:
        """扫描 memory/pending/ 中的事件，逐条写入三级记忆。"""
        pending_dir = kernel_data_dir / "memory" / "pending"
        if not pending_dir.exists():
            return []

        event_files = sorted(pending_dir.glob("event_*.json"))
        if not event_files:
            return []

        for event_file in event_files:
            try:
                data = json.loads(event_file.read_text(encoding="utf-8"))
                if not isinstance(data, dict):
                    move_to_done(event_file, pending_dir / "done")
                    continue

                event_type = str(data.get("type", "unknown"))
                summary = str(data.get("summary", ""))
                session_id = str(data.get("session_id", ""))

                if not summary and not session_id:
                    move_to_done(event_file, pending_dir / "done")
                    continue

                # 按事件类型决定角色标记
                role = "system" if event_type.startswith("exec_") else "user"

                if self.memory is not None:
                    self.memory.process_interaction(
                        content=summary,
                        role=role,
                        user_id=session_id,
                    )
                    logger.debug(
                        f"MemoryRouter: {event_type} → L1/L2/L3 "
                        f"(session={session_id})"
                    )
            except (OSError, json.JSONDecodeError) as exc:
                logger.warning(
                    f"MemoryRouter 读取事件文件失败 {event_file.name}: {exc}"
                )
            finally:
                move_to_done(event_file, pending_dir / "done")

        # 记忆由 UnifiedMemoryManager 内部持久化，无需产出 FileUpdate
        return []

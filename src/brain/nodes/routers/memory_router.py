from __future__ import annotations
import json
from pathlib import Path
from typing import Any

from src.brain.kernel.base import FileDescriptor, FilePattern, FileUpdate, Router
from src.brain.kernel.state_store import kernel_data_dir, move_to_done, next_record_id
from src.utils.log_utils import get_logger
from src.utils.time_utils import now_text

logger = get_logger("MemoryRouter")


class MemoryRouter(Router):
    """简单记忆 Router —— 原封不动记录原始事件。

    纯机械逻辑，零 LLM 调用。后续由 mem0 集成替换。

    守护 ``memory/pending/event_*.json``，将每个事件原样追加写入
    ``memory/facts.json``。通过 facts.json 中已有 ID 去重。

    处理完成的输入文件通过 :func:`move_to_done` 移入 ``done/``
    子目录（文件不可变原则）。

    提供静态辅助函数 ``lookup_facts(session_id)`` 供其他 Agent
    检索用户相关记忆。
    """

    def __init__(self, node_id: str, **config: Any) -> None:
        super().__init__(node_id)
        self._memory_dir = kernel_data_dir / "memory"
        self._facts_path = self._memory_dir / "facts.json"

    async def execute(self) -> list[FileUpdate]:
        """扫描 memory/pending/ 中的事件，原封不动记录到 facts.json。

        处理完成的输入文件通过 :func:`move_to_done` 移入 ``done/``
        子目录。
        """
        pending_dir = kernel_data_dir / "memory" / "pending"
        if not pending_dir.exists():
            return []

        event_files = sorted(pending_dir.glob("event_*.json"))
        if not event_files:
            return []

        new_facts: list[dict[str, Any]] = []
        for event_file in event_files:
            try:
                data = json.loads(event_file.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    fact = {
                        "id": f"fact_event_{data.get('id', next_record_id('fact'))}",
                        "type": "event",
                        "event_type": str(data.get("type", "unknown")),
                        "source": str(data.get("source", "")),
                        "session_id": str(data.get("session_id", "")),
                        "summary": str(data.get("summary", "")),
                        "payload": data.get("payload", {}),
                        "recorded_at": now_text(),
                    }
                    new_facts.append(fact)
            except (OSError, json.JSONDecodeError) as exc:
                logger.warning(
                    f"MemoryRouter 读取事件文件失败 {event_file.name}: {exc}"
                )
                continue

            move_to_done(event_file, pending_dir / "done")

        if not new_facts:
            return []

        existing = self._load_facts()
        existing_ids = {f.get("id", "") for f in existing}
        added = 0
        for fact in new_facts:
            if fact["id"] not in existing_ids:
                existing.append(fact)
                existing_ids.add(fact["id"])
                added += 1

        if added > 0:
            self._memory_dir.mkdir(parents=True, exist_ok=True)
            logger.info(f"MemoryRouter: 新增 {added} 条事件记录")
            return [
                FileUpdate(
                    descriptor=FileDescriptor(
                        path="memory/facts.json",
                        schema="json",
                    ),
                    content=existing,
                )
            ]

        return []

    def _load_facts(self) -> list[dict[str, Any]]:
        if not self._facts_path.exists():
            return []
        try:
            data = json.loads(self._facts_path.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except (OSError, json.JSONDecodeError):
            return []

    @staticmethod
    def lookup_facts(
        session_id: str | None = None,
        *,
        fact_type: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """静态辅助函数 —— 检索记忆事实。

        可供 PlanAgent / ExpandAgent 在运行时调用，
        获取用户相关历史。

        Parameters
        ----------
        session_id : str | None
            按 session_id 过滤，None 则返回全部。
        fact_type : str | None
            按 fact type 过滤（"event" / "plan" / "result"）。
        limit : int
            最大返回条数，默认 20。

        Returns
        -------
        list[dict[str, Any]]
            过滤后的记忆事实列表。
        """
        facts_path = kernel_data_dir / "memory" / "facts.json"
        if not facts_path.exists():
            return []
        try:
            facts = json.loads(facts_path.read_text(encoding="utf-8"))
            if not isinstance(facts, list):
                return []
        except (OSError, json.JSONDecodeError):
            return []

        result: list[dict[str, Any]] = []
        for f in facts:
            if session_id is not None and f.get("session_id") != session_id:
                continue
            if fact_type is not None and f.get("type") != fact_type:
                continue
            result.append(f)
            if len(result) >= limit:
                break
        return result

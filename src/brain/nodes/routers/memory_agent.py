from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

from src.brain.kernel.base import (
    FileDescriptor,
    FilePattern,
    FileUpdate,
    NodeState,
    Router,
)
from src.brain.kernel.state_store import next_record_id
from src.config import Config
from src.utils.log_utils import get_logger
from src.utils.time_utils import now_text

logger = get_logger("MemoryAgent")

_DATA_DIR = Config.KERNEL_DATA_DIR


class MemoryAgent(Router):
    """简单事实记忆 Router —— 从 plan 和 result 的 done/ 中提取结构化事实。

    纯机械逻辑，零 LLM 调用。后续由 mem0 集成替换。

    只读不消费：守护 ``plans/done/*.json`` 和 ``results/done/*.json``，
    提取关键字段后追加写入 ``memory/facts.json``。不修改源文件
    （文件不可变原则）。通过 facts.json 中已有 ID 去重。

    自触发 tick 确保周期性扫描（done/ 文件经由 move_to_done 到达，
    不走事件总线）。

    提供静态辅助函数 ``lookup_facts(session_id)`` 供其他 Agent
    检索用户相关记忆。
    """

    def __init__(self, node_id: str, **config: Any) -> None:
        super().__init__(node_id)
        self._memory_dir = _DATA_DIR / "memory"
        self._plans_done_dir = _DATA_DIR / "plans" / "done"
        self._results_done_dir = _DATA_DIR / "results" / "done"
        self._facts_path = self._memory_dir / "facts.json"
        self._tick_dir = _DATA_DIR / "memory"

    @property
    def type(self) -> str:
        return "router"

    @property
    def guards(self) -> list[FilePattern]:
        if self._config_watch is not None:
            return [FilePattern(p) for p in self._config_watch]
        return [
            FilePattern("plans/done/plan_*.json"),
            FilePattern("results/done/result_*.json"),
            FilePattern("memory/tick.json"),
        ]

    @property
    def produces(self) -> list[FileDescriptor]:
        if self._config_emit is not None:
            return [FileDescriptor(p) for p in self._config_emit]
        return [
            FileDescriptor("memory/facts.json"),
            FileDescriptor("memory/tick.json"),
        ]

    async def execute(self) -> list[FileUpdate]:
        """扫描 done/ 目录，提取事实（只读不消费）。

        自触发 tick 文件维持周期性扫描，确保静默到达 done/
        的文件不被遗漏。
        """
        # ── 提取事实 ──────────────────────────────────────────────────
        new_facts: list[dict[str, Any]] = []

        if self._plans_done_dir.exists():
            for plan_path in sorted(self._plans_done_dir.glob("plan_*.json")):
                fact = self._extract_plan_fact(plan_path)
                if fact:
                    new_facts.append(fact)

        if self._results_done_dir.exists():
            for result_path in sorted(self._results_done_dir.glob("result_*.json")):
                fact = self._extract_result_fact(result_path)
                if fact:
                    new_facts.append(fact)

        # ── 去重写入 ──────────────────────────────────────────────────
        updates: list[FileUpdate] = []

        if new_facts:
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
                logger.info(f"MemoryAgent: 新增 {added} 条事实")
                updates.append(
                    FileUpdate(
                        descriptor=FileDescriptor(
                            path="memory/facts.json",
                            schema="json",
                        ),
                        content=existing,
                    )
                )

        # ── 自触发 tick（限速 30s） ──────────────────────────────────
        now = time.time()
        tick_path = self._tick_dir / "tick.json"
        last_tick: float = 0.0
        if tick_path.exists():
            try:
                data = json.loads(tick_path.read_text(encoding="utf-8"))
                last_tick = float(data.get("timestamp", 0.0))
            except (OSError, json.JSONDecodeError, ValueError):
                pass

        if now - last_tick >= 30:
            self._tick_dir.mkdir(parents=True, exist_ok=True)
            tick_data = {
                "tick_id": uuid.uuid4().hex[:12],
                "timestamp": now,
            }
            updates.append(
                FileUpdate(
                    descriptor=FileDescriptor(
                        path="memory/tick.json",
                        schema="json",
                    ),
                    content=tick_data,
                )
            )

        return updates

    def on_event(self, event: FileEvent) -> bool:
        """允许自触发 —— memory tick 驱动周期性扫描。"""
        if self.state not in (NodeState.IDLE, NodeState.READY):
            return False
        return any(g.match(event.path) for g in self.guards)

    def _extract_plan_fact(self, path: Path) -> dict[str, Any] | None:
        """从 plans/done/ 中的 plan 文件提取事实（只读）。"""
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return None
        except (OSError, json.JSONDecodeError):
            return None

        return {
            "id": f"fact_plan_{data.get('id', next_record_id('fact'))}",
            "type": "plan",
            "session_id": str(data.get("session_id", "")),
            "source": str(data.get("source", "")),
            "source_event_type": str(data.get("source_event_type", "")),
            "goal": str(data.get("goal", "")),
            "summary": str(data.get("summary", "")),
            "created_at": data.get("created_at", now_text()),
        }

    def _extract_result_fact(self, path: Path) -> dict[str, Any] | None:
        """从 results/done/ 中的 result 文件提取事实（只读）。"""
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return None
        except (OSError, json.JSONDecodeError):
            return None

        return {
            "id": f"fact_result_{data.get('id', next_record_id('fact'))}",
            "type": "result",
            "command": str(data.get("command", "")),
            "judgement": str(data.get("judgement", "")),
            "reasoning": str(data.get("reasoning", "")),
            "plan_id": str(data.get("plan_id", "")),
            "action_id": str(data.get("action_id", "")),
            "created_at": data.get("created_at", now_text()),
        }

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

        可供 PlanAgent / GoalGeneratorAgent 在运行时调用，
        获取用户相关历史。

        Parameters
        ----------
        session_id : str | None
            按 session_id 过滤，None 则返回全部。
        fact_type : str | None
            按类型过滤（``"plan"`` / ``"action"``）。
        limit : int
            最大返回条数。

        Returns
        -------
        list[dict[str, Any]]
            匹配的事实记录列表（按时间倒序）。
        """
        facts_path = _DATA_DIR / "memory" / "facts.json"
        if not facts_path.exists():
            return []
        try:
            all_facts = json.loads(facts_path.read_text(encoding="utf-8"))
            if not isinstance(all_facts, list):
                return []
        except (OSError, json.JSONDecodeError):
            return []

        result: list[dict[str, Any]] = []
        for fact in reversed(all_facts):
            if not isinstance(fact, dict):
                continue
            if session_id and str(fact.get("session_id", "")) != session_id:
                continue
            if fact_type and str(fact.get("type", "")) != fact_type:
                continue
            result.append(fact)
            if len(result) >= limit:
                break
        return result

    def on_complete(self) -> None:
        if self.state != NodeState.ERROR:
            self.state = NodeState.IDLE

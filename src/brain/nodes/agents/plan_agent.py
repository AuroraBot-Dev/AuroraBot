from __future__ import annotations
import json
from pathlib import Path
from typing import Any

from src.brain.kernel.base import Agent, FileDescriptor, FilePattern, FileUpdate
from src.brain.kernel.state_store import (
    kernel_data_dir,
    move_to_done,
    next_record_id,
    parse_llm_json,
)
import src.brain.prompts as prompts
from src.utils.log_utils import get_logger
from src.utils.time_utils import now_text

logger = get_logger("PlanAgent")

_PLAN_SYSTEM_PROMPT = prompts.PLAND.get_content()


class PlanAgent(Agent):
    """从 inbox/done/ 中整合多个已完成事件生成计划的 Agent 节点。

    守护 ``inbox/done/event_*.json`` 文件。Fanout 分发后的事件
    被移入此处，Planner 按 ``session_id`` 分组整合，调用 LLM
    判断事件输入是否完整并生成 plan，写入
    ``plans/pending/plan_<id>.json``。

    LLM 调用前通过 :class:`UnifiedMemoryManager.retrieve_context`
    检索 L1/L2/L3 三级记忆，注入 prompt 辅助决策。
    处理完成的输入事件移入 ``inbox/done/archived/`` 子目录。
    LLM 不可用时回退到机械规划。
    """

    _default_guards = ["inbox/done/event_*.json"]

    def __init__(self, node_id: str, **kwargs: Any) -> None:
        super().__init__(node_id, system_prompt=_PLAN_SYSTEM_PROMPT, **kwargs)
        self._inbox_done_dir = kernel_data_dir / "inbox" / "done"
        self._plans_pending_dir = kernel_data_dir / "plans" / "pending"

    async def execute(self) -> list[FileUpdate]:
        """扫描 inbox/done/ 中的事件，按 session_id 分组整合生成 plan。

        处理完成的输入事件移入 ``inbox/done/archived/`` 子目录。
        """
        if not self._inbox_done_dir.exists():
            return []

        event_files = sorted(self._inbox_done_dir.glob("event_*.json"))
        if not event_files:
            return []

        grouped = self._group_by_session(event_files)
        if not grouped:
            return []

        self._plans_pending_dir.mkdir(parents=True, exist_ok=True)
        archived_dir = self._inbox_done_dir / "archived"
        archived_dir.mkdir(parents=True, exist_ok=True)
        updates: list[FileUpdate] = []

        for session_id, events in grouped.items():
            try:
                if not events:
                    continue

                plan = await self._generate_plan(session_id, events)
                if plan is None:
                    continue

                plan_id = str(plan["id"])
                updates.append(
                    FileUpdate(
                        descriptor=FileDescriptor(
                            path=f"plans/pending/plan_{plan_id}.json",
                            schema="json",
                        ),
                        content=plan,
                    )
                )
                logger.info(
                    f"PlanAgent: session={session_id} 整合 {len(events)} 个事件 → plan={plan_id}"
                )

            except Exception:
                logger.exception(f"PlanAgent session={session_id} 整合失败")

            for event_file in [e["_path"] for e in events]:
                move_to_done(event_file, archived_dir)

        return updates

    async def _generate_plan(
        self, session_id: str, events: list[dict[str, Any]]
    ) -> dict[str, Any] | None:
        """调用 LLM 整合多个事件为一个 plan。"""
        events_display = []
        for ev in events:
            events_display.append(
                {
                    "id": ev.get("id", ""),
                    "type": ev.get("type", "unknown"),
                    "source": ev.get("source", ""),
                    "summary": ev.get("summary", ""),
                    "payload": ev.get("payload", {}),
                }
            )
        event_json = json.dumps(events_display, indent=2, ensure_ascii=False)

        # 检索三级记忆上下文
        memory_text = ""
        if self.memory is not None:
            query = str(events[0].get("summary", "")) if events else ""
            ctx = self.memory.retrieve_context(
                current_query=query, user_id=session_id
            )
            memory_text = ctx.to_prompt_text()

        user_msg = (
            f"session_id: {session_id}\n"
            f"当前轮次事件 ({len(events)} 个):\n{event_json}"
        )
        if memory_text:
            user_msg += f"\n\n【历史记忆】\n{memory_text}"
        user_msg += (
            f"\n\n请判断这些事件是否构成一个完整的用户意图，生成计划。"
        )
        messages = [{"role": "user", "content": user_msg}]

        try:
            raw = await self.think(messages, max_tokens=512)
        except Exception:
            logger.exception("PlanAgent LLM 调用失败，回退到机械规划")
            return self._fallback_plan(session_id, events)

        parsed = parse_llm_json(raw)
        if parsed is None:
            logger.warning(f"PlanAgent LLM 输出不可解析，回退到机械规划: {raw!r}")
            return self._fallback_plan(session_id, events)

        merged_event = events[0] if events else {}
        return self._build_plan(merged_event, parsed, session_id)

    def _build_plan(
        self,
        primary_event: dict[str, Any],
        llm_output: dict[str, Any],
        session_id: str,
    ) -> dict[str, Any]:
        timestamp = now_text()
        return {
            "id": next_record_id("plan"),
            "source_event_id": str(primary_event.get("id", "")),
            "source_event_type": str(primary_event.get("type", "unknown")),
            "source": str(primary_event.get("source", "")),
            "session_id": session_id,
            "goal": str(llm_output.get("goal", "")),
            "reasoning": str(llm_output.get("reasoning", "")),
            "summary": str(primary_event.get("summary", "")),
            "payload": primary_event.get("payload", {}),
            "priority": int(llm_output.get("priority", 50)),
            "suggested_actions": int(llm_output.get("suggested_actions", 1)),
            "created_at": timestamp,
        }

    def _fallback_plan(
        self, session_id: str, events: list[dict[str, Any]]
    ) -> dict[str, Any] | None:
        """LLM 不可用时的机械回退。"""
        if not events:
            return None
        primary = events[0]
        timestamp = now_text()
        summaries = [
            str(e.get("summary", "")) for e in events if str(e.get("summary", ""))
        ]
        return {
            "id": next_record_id("plan"),
            "source_event_id": str(primary.get("id", "")),
            "source_event_type": str(primary.get("type", "unknown")),
            "source": str(primary.get("source", "")),
            "session_id": session_id,
            "goal": "; ".join(summaries)
            or f"处理 session {session_id} 的 {len(events)} 个事件",
            "reasoning": "LLM 不可用，使用机械回退",
            "summary": ", ".join(summaries),
            "payload": primary.get("payload", {}),
            "priority": 50,
            "suggested_actions": min(len(events), 3),
            "created_at": timestamp,
        }

    @staticmethod
    def _read_event(path: Path) -> dict[str, Any] | None:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else None
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning(f"读取事件文件失败 {path}: {exc}")
            return None

    def _group_by_session(self, paths: list[Path]) -> dict[str, list[dict[str, Any]]]:
        """按 session_id 分组，返回有序字典（FIFO 保持时间序）。"""
        grouped: dict[str, list[dict[str, Any]]] = {}
        for path in paths:
            data = self._read_event(path)
            if data is None:
                continue
            sid = str(data.get("session_id", ""))
            data["_path"] = path
            if sid not in grouped:
                grouped[sid] = []
            grouped[sid].append(data)
        return dict(grouped)

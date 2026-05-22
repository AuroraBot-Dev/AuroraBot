from __future__ import annotations
import json
from pathlib import Path
from typing import Any

from src.brain.kernel.base import Agent, FileDescriptor, FilePattern, FileUpdate
from src.brain.kernel.state_store import kernel_data_dir, parse_llm_json
from src.utils.log_utils import get_logger
from src.utils.time_utils import now_text
import src.brain.prompts as prompts

logger = get_logger("GoalGeneratorAgent")

_GOAL_SYSTEM_PROMPT = prompts.GOAL.get_content()


class GoalGeneratorAgent(Agent):
    """自发目标生成 Agent —— 在系统空闲时主动产生意图。

    守护 ``heartbeat/tick.json``。每次心跳唤醒，检查系统状态
    （pending plan、最近活动、时段），调用 LLM 判断是否需要
    生成自发目标。绝大多数时候返回 ``action: "none"``。

    生成的目标写入 ``intent/pending/goal_<id>.json``，
    被 PlanAgent 的下游流程处理。

    冷却机制：两次 LLM 调用之间至少间隔 ``cooldown_ticks`` 个 tick，
    中间 tick 直接跳过。
    """

    _default_guards = ["heartbeat/tick.json"]
    _default_produces = ["intent/pending/goal.json"]

    def __init__(self, node_id: str, **config: Any) -> None:
        super().__init__(node_id, system_prompt=_GOAL_SYSTEM_PROMPT)
        self._intent_pending_dir = kernel_data_dir / "intent" / "pending"
        self._plans_pending_dir = kernel_data_dir / "plans" / "pending"
        self._heartbeat_dir = kernel_data_dir / "heartbeat"
        # 冷却：每 N 个 tick 才真正调用一次 LLM
        self._cooldown_ticks = int(config.get("cooldown_ticks", 6))
        self._tick_count = 0
        self._last_goal_at: str | None = None  # 上次生成目标的时间

    async def execute(self) -> list[FileUpdate]:
        self._tick_count += 1
        if self._tick_count % self._cooldown_ticks != 0:
            return []  # 冷却中，跳过

        # 检查系统状态
        state = self._gather_state()
        state_json = json.dumps(state, indent=2, ensure_ascii=False)

        user_msg = (
            f"当前系统状态:\n{state_json}\n\n"
            f"请判断是否需要生成自发目标。默认：不做任何事。"
        )
        messages = [{"role": "user", "content": user_msg}]

        try:
            raw = await self.think(messages, max_tokens=256)
        except Exception:
            logger.exception("GoalGeneratorAgent LLM 调用失败")
            return []

        parsed = parse_llm_json(raw)
        if parsed is None:
            logger.warning(f"GoalGeneratorAgent LLM 输出不可解析: {raw!r}")
            return []

        action = str(parsed.get("action", "none")).strip().lower()
        if action != "generate":
            logger.debug(
                f"GoalGenerator: 选择不做任何事 — {parsed.get('reasoning', '')}"
            )
            return []

        goal_text = str(parsed.get("goal", "")).strip()
        if not goal_text:
            return []

        priority = min(int(parsed.get("priority", 30)), 50)

        self._intent_pending_dir.mkdir(parents=True, exist_ok=True)
        timestamp = now_text()

        goal_data = {
            "id": f"goal_{timestamp}",
            "goal": goal_text,
            "reasoning": str(parsed.get("reasoning", "")),
            "priority": priority,
            "source": "goal_generator",
            "created_at": timestamp,
        }

        goal_path = f"intent/pending/goal_{timestamp}.json"
        self._last_goal_at = timestamp

        logger.info(f"GoalGenerator: 生成自发目标 — {goal_text} (priority={priority})")

        return [
            FileUpdate(
                descriptor=FileDescriptor(
                    path=goal_path,
                    schema="json",
                ),
                content=goal_data,
            )
        ]

    def _gather_state(self) -> dict[str, Any]:
        """收集当前系统状态供 LLM 判断。

        文件位置（pending/）即表达状态，不再依赖 status 字段。
        """
        pending_count = 0
        recent_plans: list[dict[str, Any]] = []
        if self._plans_pending_dir.exists():
            for plan_path in sorted(
                self._plans_pending_dir.glob("plan_*.json"), reverse=True
            ):
                try:
                    data = json.loads(plan_path.read_text(encoding="utf-8"))
                    if isinstance(data, dict):
                        pending_count += 1
                        if len(recent_plans) < 5:
                            recent_plans.append(
                                {
                                    "goal": data.get("goal", ""),
                                    "created_at": data.get("created_at", ""),
                                }
                            )
                except (OSError, json.JSONDecodeError):
                    continue

        last_tick_ago = ""
        tick_path = self._heartbeat_dir / "tick.json"
        if tick_path.exists():
            try:
                import time as _time

                data = json.loads(tick_path.read_text(encoding="utf-8"))
                last_ts = float(data.get("timestamp", 0))
                last_tick_ago = f"{_time.time() - last_ts:.0f}s ago"
            except (OSError, json.JSONDecodeError, ValueError):
                pass

        return {
            "pending_plans": pending_count,
            "recent_plans": recent_plans,
            "last_goal_at": self._last_goal_at,
            "last_tick": last_tick_ago,
        }

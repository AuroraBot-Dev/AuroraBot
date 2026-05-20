from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.brain.kernel.base import (
    Agent,
    FileDescriptor,
    FilePattern,
    FileUpdate,
    NodeState,
)
from src.brain.kernel.state_store import parse_llm_json
from src.config import Config
from src.utils.log_utils import get_logger
from src.utils.time_utils import now_text

logger = get_logger("GoalGeneratorAgent")

_DATA_DIR = Config.KERNEL_DATA_DIR

_GOAL_SYSTEM_PROMPT = """\
你是 AuroraBot 的自发目标生成节点。你的默认行为是**不做任何事**。

只有当以下条件**同时**满足时，才生成自发目标：
1. 系统确实空闲（没有 pending 状态的 plan）
2. 当前时段有明确、自然、值得做的事
3. 行为不会让人感到突兀或厌烦

输出严格 JSON（二选一）：
不做任何事：{"action": "none", "reasoning": "为什么不做"}
生成目标：{"action": "generate", "goal": "清晰可执行的目标", "priority": 30, "reasoning": "为什么现在适合做这件事"}

规则：
- **宁可错过，不要烦人。** 任何犹豫时选 "none"
- 两次自发行为之间至少间隔数小时——你不是闹钟
- 深夜（23:00-07:00）：只做道晚安，不做其他
- priority 永远不超过 50（自发目标优先级永远低于用户请求）
- 如果最近有用户互动，优先回应用户而不是生成自发目标
- 不要重复刚做过的目标
"""


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

    def __init__(self, node_id: str, **config: Any) -> None:
        super().__init__(node_id, system_prompt=_GOAL_SYSTEM_PROMPT)
        self._intent_pending_dir = _DATA_DIR / "intent" / "pending"
        self._plans_pending_dir = _DATA_DIR / "plans" / "pending"
        self._heartbeat_dir = _DATA_DIR / "heartbeat"
        # 冷却：每 N 个 tick 才真正调用一次 LLM
        self._cooldown_ticks = int(config.get("cooldown_ticks", 6))
        self._tick_count = 0
        self._last_goal_at: str | None = None  # 上次生成目标的时间

    @property
    def type(self) -> str:
        return "agent"

    @property
    def guards(self) -> list[FilePattern]:
        if self._config_watch is not None:
            return [FilePattern(p) for p in self._config_watch]
        return [FilePattern("heartbeat/tick.json")]

    @property
    def produces(self) -> list[FileDescriptor]:
        if self._config_emit is not None:
            return [FileDescriptor(p) for p in self._config_emit]
        return [FileDescriptor("intent/pending/goal.json")]

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
            logger.warning(
                f"GoalGeneratorAgent LLM 输出不可解析: {raw!r}"
            )
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

        logger.info(
            f"GoalGenerator: 生成自发目标 — {goal_text} (priority={priority})"
        )

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
                            recent_plans.append({
                                "goal": data.get("goal", ""),
                                "created_at": data.get("created_at", ""),
                            })
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

    def on_complete(self) -> None:
        if self.state != NodeState.ERROR:
            self.state = NodeState.IDLE

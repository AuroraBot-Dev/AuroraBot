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

logger = get_logger("ReflexLearnerAgent")

_DATA_DIR = Config.KERNEL_DATA_DIR

_LEARNER_SYSTEM_PROMPT = """\
你是 AuroraBot 的反射学习节点。扫描最近的对话与执行记录，
识别可以缓存为反射规则的重复 Q&A 模式，以减少 LLM 推理消耗。

你会收到两部分：
1. recent_actions: 最近完成的 action 记录（command + kwargs + result）
2. recent_plans: 最近完成的 plan 记录（goal + summary）
3. existing_rules: 当前已有的反射规则

输出严格 JSON：
{
  "new_rules": [
    {
      "pattern": "晚安",
      "pattern_type": "contains",
      "response": "晚安~",
      "confidence": 0.8,
      "reasoning": "用户多次说晚安，机器人回复晚安"
    }
  ],
  "deprecate_ids": [],
  "reasoning": "总体判断"
}

规则：
- 只提取真正重复的、简单的 Q&A（如问候、晚安、简单确认）
- 复杂对话或需要语境理解的不要缓存
- pattern_type 选 contains / exact / starts_with / ends_with
- 新规则 confidence 从 0.7 起步，不要超过 0.85
- 对命中率低或过时的规则，通过 deprecate_ids 列表标记淘汰
- 如果本次没有值得提取的规则，返回空数组
- **宁可少缓存，不要乱匹配**
"""


class ReflexLearnerAgent(Agent):
    """反射规则学习 Agent —— 从历史中提取可缓存的 Q&A 模式。

    守护 ``heartbeat/tick.json``。周期性（冷却机制）扫描近期
    完成的 plan 和 action，调用 LLM 识别重复模式，
    生成/更新 ``reflexes/rules.json``。

    同时负责淘汰低质量规则：命中率低、长期未命中、置信度衰减。
    """

    def __init__(self, node_id: str, **config: Any) -> None:
        super().__init__(node_id, system_prompt=_LEARNER_SYSTEM_PROMPT)
        self._plans_done_dir = _DATA_DIR / "plans" / "done"
        self._results_done_dir = _DATA_DIR / "results" / "done"
        self._rules_path = _DATA_DIR / "reflexes" / "rules.json"
        # 冷却：每 N 个 tick 才学习一次（比 GoalGenerator 更稀疏）
        self._cooldown_ticks = int(config.get("cooldown_ticks", 12))
        self._tick_count = 0
        # 机械衰减：低置信度 + 低命中 → 自动淘汰
        self._mechanical_decay = float(config.get("mechanical_decay", 0.02))
        self._min_confidence = float(config.get("min_confidence", 0.3))

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
        return [FileDescriptor("reflexes/rules.json")]

    async def execute(self) -> list[FileUpdate]:
        self._tick_count += 1
        if self._tick_count % self._cooldown_ticks != 0:
            return []

        existing_rules = self._load_rules()

        # 先做机械衰减：对每条规则降 confidence + 淘汰低质
        rules_changed = self._mechanical_prune(existing_rules)

        # 收集近期记录
        recent_actions = self._scan_recent(self._results_done_dir, "result_*.json", limit=20)
        recent_plans = self._scan_recent(self._plans_done_dir, "plan_*.json", limit=20)

        if not recent_actions and not recent_plans:
            if rules_changed:
                return self._make_rules_update(existing_rules)
            return []

        # 调用 LLM 学习
        user_msg = (
            f"recent_actions:\n{json.dumps(recent_actions, indent=2, ensure_ascii=False)}\n\n"
            f"recent_plans:\n{json.dumps(recent_plans, indent=2, ensure_ascii=False)}\n\n"
            f"existing_rules:\n{json.dumps(existing_rules, indent=2, ensure_ascii=False)}\n\n"
            f"分析以上数据，提取新的反射规则或标记淘汰。"
        )
        messages = [{"role": "user", "content": user_msg}]

        try:
            raw = await self.think(messages, max_tokens=1024)
        except Exception:
            logger.exception("ReflexLearnerAgent LLM 调用失败")
            if rules_changed:
                return self._make_rules_update(existing_rules)
            return []

        parsed = parse_llm_json(raw)
        if parsed is None:
            logger.warning(
                f"ReflexLearnerAgent LLM 输出不可解析: {raw!r}"
            )
            if rules_changed:
                return self._make_rules_update(existing_rules)
            return []

        # 添加新规则
        new_rules = parsed.get("new_rules", [])
        if isinstance(new_rules, list):
            for nr in new_rules:
                if not isinstance(nr, dict):
                    continue
                pattern = str(nr.get("pattern", "")).strip()
                response = str(nr.get("response", "")).strip()
                if not pattern or not response:
                    continue

                # 去重：相同 pattern + response 不重复添加
                if any(
                    r.get("pattern") == pattern and r.get("response") == response
                    for r in existing_rules
                ):
                    continue

                existing_rules.append({
                    "id": f"reflex_{now_text().replace(':', '-')}",
                    "pattern": pattern,
                    "pattern_type": str(nr.get("pattern_type", "contains")),
                    "response": response,
                    "command": "im.polaris.qq.send_qq_message",
                    "confidence": min(
                        float(nr.get("confidence", 0.7)), 0.85
                    ),
                    "hit_count": 0,
                    "created_at": now_text(),
                    "last_hit_at": None,
                    "reasoning": str(nr.get("reasoning", "")),
                })
                logger.info(
                    f"ReflexLearner: 新增规则 pattern={pattern!r} "
                    f"response={response!r}"
                )

        # 淘汰标记的规则
        deprecate_ids = parsed.get("deprecate_ids", [])
        if isinstance(deprecate_ids, list):
            deprecated = set(str(did) for did in deprecate_ids)
            before = len(existing_rules)
            existing_rules = [
                r for r in existing_rules
                if str(r.get("id", "")) not in deprecated
            ]
            if len(existing_rules) < before:
                logger.info(
                    f"ReflexLearner: LLM 淘汰 {before - len(existing_rules)} 条规则"
                )

        return self._make_rules_update(existing_rules)

    def _mechanical_prune(self, rules: list[dict[str, Any]]) -> bool:
        """机械衰减与淘汰：降低低命中规则的置信度，淘汰低于阈值的。"""
        changed = False
        surviving: list[dict[str, Any]] = []
        for rule in rules:
            confidence = float(rule.get("confidence", 0.7))
            hit_count = int(rule.get("hit_count", 0))

            # 如果从未命中且存在超过一定时间，衰减置信度
            if hit_count == 0 and rule.get("created_at"):
                confidence -= self._mechanical_decay

            if confidence < self._min_confidence:
                logger.info(
                    f"ReflexLearner: 机械淘汰规则 pattern={rule.get('pattern', '')!r} "
                    f"(confidence={confidence:.2f})"
                )
                changed = True
                continue

            if abs(confidence - float(rule.get("confidence", 0.7))) > 0.001:
                rule["confidence"] = round(confidence, 3)
                changed = True

            surviving.append(rule)

        rules.clear()
        rules.extend(surviving)
        return changed

    def _scan_recent(
        self, directory: Path, glob_pattern: str, limit: int
    ) -> list[dict[str, Any]]:
        if not directory.exists():
            return []
        results: list[dict[str, Any]] = []
        for file_path in sorted(directory.glob(glob_pattern), reverse=True):
            if len(results) >= limit:
                break
            try:
                data = json.loads(file_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    # 只取关键字段，减少 token
                    results.append({
                        k: data.get(k)
                        for k in ("goal", "status", "command", "kwargs", "result",
                                   "reasoning", "created_at", "summary")
                        if k in data
                    })
            except (OSError, json.JSONDecodeError):
                continue
        return results

    def _load_rules(self) -> list[dict[str, Any]]:
        if not self._rules_path.exists():
            return []
        try:
            data = json.loads(self._rules_path.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning(f"ReflexLearnerAgent 读取规则文件失败: {exc}")
            return []

    def _make_rules_update(
        self, rules: list[dict[str, Any]]
    ) -> list[FileUpdate]:
        return [
            FileUpdate(
                descriptor=FileDescriptor(
                    path="reflexes/rules.json",
                    schema="json",
                ),
                content=rules,
            )
        ]

    def on_complete(self) -> None:
        if self.state != NodeState.ERROR:
            self.state = NodeState.IDLE

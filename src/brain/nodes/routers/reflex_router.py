from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.brain.kernel.base import (
    FileDescriptor,
    FilePattern,
    FileUpdate,
    NodeState,
    Router,
)
from src.brain.kernel.state_store import move_to_done, next_record_id
from src.config import Config
from src.utils.log_utils import get_logger
from src.utils.time_utils import now_text

logger = get_logger("ReflexRouter")

_DATA_DIR = Config.KERNEL_DATA_DIR

# 支持的匹配模式
_MATCHERS: dict[str, Any] = {
    "contains": lambda text, pattern: pattern in text,
    "exact": lambda text, pattern: text.strip() == pattern.strip(),
    "starts_with": lambda text, pattern: text.strip().startswith(pattern.strip()),
    "ends_with": lambda text, pattern: text.strip().endswith(pattern.strip()),
}


class ReflexRouter(Router):
    """反射匹配 Router —— 消息命中缓存规则时直接产出 action，跳过 LLM。

    纯机械逻辑，零 LLM 调用。

    守护 ``fanout/to-reflex/pending/event_*.json`` 和
    ``reflexes/rules.json``。对每条消息读取 ``reflexes/rules.json``
    做规则匹配：
    - 命中 → 直接写 action 到 ``actions/pending/``
    - 未命中 → 返回空，留给 PlanAgent 全链路

    处理完成的输入文件通过 :func:`move_to_done` 移入 ``done/``
    子目录（不再直接删除）。

    参数在构造时通过 ``**config`` 传入：
    - ``min_confidence``: 最低置信度阈值，默认 0.7
    - ``rules_path``: 规则文件路径，默认 ``reflexes/rules.json``
    """

    def __init__(self, node_id: str, **config: Any) -> None:
        super().__init__(node_id)
        self._min_confidence = float(config.get("min_confidence", 0.7))
        self._rules_path = str(config.get("rules_path", "reflexes/rules.json"))
        self._actions_pending_dir = _DATA_DIR / "actions" / "pending"

    @property
    def type(self) -> str:
        return "router"

    @property
    def guards(self) -> list[FilePattern]:
        if self._config_watch is not None:
            return [FilePattern(p) for p in self._config_watch]
        return [
            FilePattern("fanout/to-reflex/pending/event_*.json"),
            FilePattern("reflexes/rules.json"),
        ]

    @property
    def produces(self) -> list[FileDescriptor]:
        if self._config_emit is not None:
            return [FileDescriptor(p) for p in self._config_emit]
        return [FileDescriptor("actions/pending/action.json")]

    async def execute(self) -> list[FileUpdate]:
        """扫描匹配的事件文件，对文本做规则匹配并产出 action。

        处理完成的输入文件通过 :func:`move_to_done` 移入 ``done/``
        子目录（不再直接 ``unlink``）。
        """
        rules = self._load_rules()
        if not rules:
            return []

        # ── 收集事件文件（跳过 rules.json 模式） ────────────────────
        watch_patterns = self._config_watch or [
            "fanout/to-reflex/pending/event_*.json",
            "reflexes/rules.json",
        ]
        event_files: list[Path] = []
        for pattern in watch_patterns:
            if "rules.json" in pattern:
                continue
            guard_path = _DATA_DIR / pattern
            parent = guard_path.parent
            pattern_name = guard_path.name
            if parent.exists():
                event_files.extend(sorted(parent.glob(pattern_name)))

        if not event_files:
            return []

        updates: list[FileUpdate] = []
        self._actions_pending_dir.mkdir(parents=True, exist_ok=True)

        for event_file in event_files:
            try:
                event_data = self._read_event(event_file)
                if event_data is None:
                    move_to_done(event_file, event_file.parent / "done")
                    continue

                payload = event_data.get("payload", {})
                if not isinstance(payload, dict):
                    payload = {}
                text = str(payload.get("text", "")).strip()
                if not text:
                    move_to_done(event_file, event_file.parent / "done")
                    continue

                match = self._match_rules(text, rules)
                if match is None:
                    # 未命中 — fanout 已将副本发给 planner 全链路，此处直接消费
                    move_to_done(event_file, event_file.parent / "done")
                    continue

                # 命中 → 直接创建 action
                action = self._build_action(event_data, match)
                action_id = str(action["id"])

                updates.append(
                    FileUpdate(
                        descriptor=FileDescriptor(
                            path=f"actions/pending/action_{action_id}.json",
                            schema="json",
                        ),
                        content=action,
                    )
                )

                # 消费输入
                move_to_done(event_file, event_file.parent / "done")

                # 更新规则命中计数
                rule = match["_rule"]
                rule["hit_count"] = rule.get("hit_count", 0) + 1
                rule["last_hit_at"] = now_text()
                self._save_rules(rules)

                logger.info(
                    f"ReflexRouter: 命中规则 → action={action_id}, "
                    f"pattern={rule['pattern']!r}"
                )

            except Exception:
                logger.exception(
                    f"ReflexRouter 处理事件文件失败: {event_file.name}"
                )

        return updates

    def _match_rules(
        self, text: str, rules: list[dict[str, Any]]
    ) -> dict[str, Any] | None:
        """按置信度降序遍历规则，返回第一个命中的 match 信息。"""
        sorted_rules = sorted(
            rules,
            key=lambda r: r.get("confidence", 0),
            reverse=True,
        )
        for rule in sorted_rules:
            if float(rule.get("confidence", 0)) < self._min_confidence:
                continue
            pattern = str(rule.get("pattern", ""))
            pattern_type = str(rule.get("pattern_type", "contains"))
            matcher = _MATCHERS.get(pattern_type)
            if matcher is None:
                continue
            if matcher(text, pattern):
                return {
                    "command_name": str(rule.get("command", "im.polaris.qq.send_qq_message")),
                    "kwargs": {
                        "text": str(rule.get("response", "")),
                    },
                    "reasoning": f"反射命中: {pattern_type}={pattern!r}, confidence={rule.get('confidence', 0)}",
                    "_rule": rule,
                }
        return None

    def _build_action(
        self, event_data: dict[str, Any], match: dict[str, Any]
    ) -> dict[str, Any]:
        timestamp = now_text()
        session_id = str(event_data.get("session_id", ""))
        kwargs = dict(match.get("kwargs", {}))
        # 注入 session_id（规则中的占位由实际事件填充）
        if session_id and "session_id" not in kwargs:
            kwargs["session_id"] = session_id
        return {
            "id": next_record_id("action"),
            "plan_id": "reflex",  # 无 plan，标记为 reflex 直出
            "source_event_id": event_data.get("id", ""),
            "command": match.get("command_name", "im.polaris.qq.send_qq_message"),
            "kwargs": kwargs,
            "reasoning": match.get("reasoning", ""),
            "created_at": timestamp,
        }

    def _load_rules(self) -> list[dict[str, Any]]:
        rules_path = _DATA_DIR / self._rules_path
        if not rules_path.exists():
            return []
        try:
            data = json.loads(rules_path.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning(f"ReflexRouter 读取规则文件失败: {exc}")
            return []

    def _save_rules(self, rules: list[dict[str, Any]]) -> None:
        rules_path = _DATA_DIR / self._rules_path
        rules_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            rules_path.write_text(
                json.dumps(rules, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except OSError as exc:
            logger.warning(f"ReflexRouter 保存规则文件失败: {exc}")

    @staticmethod
    def _read_event(path: Path) -> dict[str, Any] | None:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else None
        except (OSError, json.JSONDecodeError):
            return None

    def on_complete(self) -> None:
        if self.state != NodeState.ERROR:
            self.state = NodeState.IDLE

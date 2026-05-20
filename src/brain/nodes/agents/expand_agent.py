from __future__ import annotations

import json
from pathlib import Path
from typing import Any, TYPE_CHECKING

from src.brain.kernel.base import (
    Agent,
    FileDescriptor,
    FilePattern,
    FileUpdate,
    NodeState,
)
from src.brain.kernel.state_store import move_to_done, next_record_id, parse_llm_json
from src.config import Config
from src.utils.log_utils import get_logger
from src.utils.time_utils import now_text

if TYPE_CHECKING:
    from src.platform.application_host import ApplicationHost
    from src.platform.contracts import CommandSpec

logger = get_logger("ExpandAgent")

_DATA_DIR = Config.KERNEL_DATA_DIR

_EXPAND_SYSTEM_PROMPT = """\
你是 AuroraBot 的行动展开节点。根据计划选择合适的命令并构造参数。

你会收到两个部分：
1. plan：包含 goal、summary、payload、source_event_type 的计划对象
2. commands：可用命令列表，每个命令有 name、description、params（parameters_schema）

输出严格 JSON：
{
  "actions": [
    {
      "command_name": "im.polaris.xxx.yyy",
      "kwargs": {},
      "reasoning": "为什么选这个命令"
    }
  ]
}

规则：
- 根据 plan.goal 和 plan.summary 语义匹配最合适的命令
- 从 plan.payload 和上下文推断 kwargs
- 如果找不到合适命令，返回空 actions 数组
- 优先选专用命令，其次通用命令
- kwargs 必须符合命令 params 中声明的 schema
- 支持一个 plan 展开为多个 action
"""


class ExpandAgent(Agent):
    """将 plan 展开为具体 action 的 Agent 节点。

    守护 ``plans/pending/plan_*.json`` 文件，当新的 pending plan
    到达时，从宿主获取可用命令列表，调用 LLM 语义匹配命令并构
    造参数，写入 ``actions/pending/action_<id>.json``。

    支持一个 plan 展开为多个 action。
    处理完成的输入 plan 通过 :func:`move_to_done` 移入 ``done/``
    子目录（文件不可变原则，不再原地修改 status 字段）。
    """

    def __init__(self, node_id: str, host: ApplicationHost) -> None:  # noqa: F821
        super().__init__(node_id, host, system_prompt=_EXPAND_SYSTEM_PROMPT)
        self._plans_pending_dir = _DATA_DIR / "plans" / "pending"
        self._actions_pending_dir = _DATA_DIR / "actions" / "pending"

    @property
    def type(self) -> str:
        return "agent"

    @property
    def guards(self) -> list[FilePattern]:
        if self._config_watch is not None:
            return [FilePattern(p) for p in self._config_watch]
        return [FilePattern("plans/pending/plan_*.json")]

    @property
    def produces(self) -> list[FileDescriptor]:
        if self._config_emit is not None:
            return [FileDescriptor(p) for p in self._config_emit]
        return [FileDescriptor("actions/pending/action.json")]

    async def execute(self) -> list[FileUpdate]:
        """扫描 plans/pending/ 中的 plan，调用 LLM 生成 action。

        处理完成的输入 plan 通过 :func:`move_to_done` 移入 ``done/``
        子目录（不再原地修改 status 字段）。
        """
        commands = self._host.list_command_specs()
        if not commands:
            return []

        if not self._plans_pending_dir.exists():
            return []

        pending_plans = self._scan_pending_plans()
        if not pending_plans:
            return []

        self._actions_pending_dir.mkdir(parents=True, exist_ok=True)
        updates: list[FileUpdate] = []

        for plan_path, plan_data in pending_plans:
            try:
                actions_spec = await self._expand_plan(plan_data, commands)
                if not actions_spec:
                    # LLM 认为无需行动 → 仅消费输入
                    move_to_done(plan_path, plan_path.parent / "done")
                    continue

                action_ids: list[str] = []
                for spec in actions_spec:
                    action = self._build_action(plan_data, spec)
                    action_id = str(action["id"])
                    action_ids.append(action_id)
                    updates.append(
                        FileUpdate(
                            descriptor=FileDescriptor(
                                path=f"actions/pending/action_{action_id}.json",
                                schema="json",
                            ),
                            content=action,
                        )
                    )

                # 消费输入 plan
                move_to_done(plan_path, plan_path.parent / "done")

            except Exception:
                logger.exception(f"ExpandAgent 展开 plan 失败: {plan_path.name}")

        return updates

    async def _expand_plan(
        self,
        plan: dict[str, Any],
        commands: list[CommandSpec],  # noqa: F821
    ) -> list[dict[str, Any]] | None:
        """调用 LLM 匹配命令并构造 kwargs。"""
        plan_info = {
            "goal": plan.get("goal", ""),
            "summary": plan.get("summary", ""),
            "source_event_type": plan.get("source_event_type", ""),
            "session_id": plan.get("session_id", ""),
            "payload": plan.get("payload", {}),
        }
        cmd_info = [
            {
                "name": c.name,
                "description": c.description,
                "params": c.parameters_schema,
            }
            for c in commands
        ]

        user_msg = (
            f"plan:\n{json.dumps(plan_info, indent=2, ensure_ascii=False)}\n\n"
            f"commands:\n{json.dumps(cmd_info, indent=2, ensure_ascii=False)}\n\n"
            f"请为这个 plan 选择命令。"
        )
        messages = [{"role": "user", "content": user_msg}]

        try:
            raw = await self.think(messages, max_tokens=1024)
        except Exception:
            logger.exception("ExpandAgent LLM 调用失败，回退到机械匹配")
            return self._fallback_expand(plan, commands)

        parsed = parse_llm_json(raw)
        if parsed is None:
            logger.warning(f"ExpandAgent LLM 输出不可解析，回退到机械匹配: {raw!r}")
            return self._fallback_expand(plan, commands)

        actions = parsed.get("actions")
        if not isinstance(actions, list) or not actions:
            logger.info("ExpandAgent: LLM 返回空 actions，跳过")
            return []

        # 过滤掉 command_name 不在可用列表中的幻觉
        valid_names = {c.name for c in commands}
        result: list[dict[str, Any]] = []
        for act in actions:
            if not isinstance(act, dict):
                continue
            cmd_name = str(act.get("command_name", ""))
            if cmd_name not in valid_names:
                logger.warning(f"ExpandAgent: LLM 幻觉命令 {cmd_name}，已忽略")
                continue
            result.append(
                {
                    "command_name": cmd_name,
                    "kwargs": (
                        act.get("kwargs", {})
                        if isinstance(act.get("kwargs"), dict)
                        else {}
                    ),
                    "reasoning": str(act.get("reasoning", "")),
                }
            )
        return result

    def _build_action(
        self,
        plan: dict[str, Any],
        spec: dict[str, Any],
    ) -> dict[str, Any]:
        timestamp = now_text()
        return {
            "id": next_record_id("action"),
            "plan_id": plan.get("id", ""),
            "source_event_id": plan.get("source_event_id", ""),
            "command": spec["command_name"],
            "kwargs": spec.get("kwargs", {}),
            "reasoning": spec.get("reasoning", ""),
            "created_at": timestamp,
        }

    def _fallback_expand(
        self,
        plan: dict[str, Any],
        commands: list[CommandSpec],  # noqa: F821
    ) -> list[dict[str, Any]] | None:
        """LLM 不可用时的机械命令匹配回退。"""
        if not commands:
            return None
        # 选第一个可用命令作为回退
        cmd = commands[0]
        return [
            {
                "command_name": cmd.name,
                "kwargs": {},
                "reasoning": "LLM 不可用，使用机械回退（首个命令）",
            }
        ]

    def _scan_pending_plans(
        self,
    ) -> list[tuple[Path, dict[str, Any]]]:
        """扫描 plans/pending/ 目录，返回所有 plan 文件。

        文件位置（pending/）即表达状态，不再依赖文件的 status 字段。
        """
        pending: list[tuple[Path, dict[str, Any]]] = []
        for plan_path in sorted(self._plans_pending_dir.glob("plan_*.json")):
            try:
                data = json.loads(plan_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    pending.append((plan_path, data))
            except (OSError, json.JSONDecodeError) as exc:
                logger.warning(f"读取 plan 文件失败 {plan_path.name}: {exc}")
        return pending

    def on_complete(self) -> None:
        if self.state != NodeState.ERROR:
            self.state = NodeState.IDLE

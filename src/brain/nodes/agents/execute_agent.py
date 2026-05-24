from __future__ import annotations
import json
from pathlib import Path
from typing import Any, TYPE_CHECKING

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

if TYPE_CHECKING:
    from src.platform.application_host import ApplicationHost

logger = get_logger("ExecuteAgent")

_EXECUTE_SYSTEM_PROMPT = prompts.EXEC.get_content()


class ExecuteAgent(Agent):
    """执行 action 并理解结果的 Agent 节点。

    守护 ``actions/pending/action_*.json`` 文件，当新的 pending action
    到达时，调用宿主命令执行，将结果交给 LLM 判断状态
    （done / failed / retry），写入 ``results/pending/result_<id>.json``。

    处理完成的输入 action 通过 :func:`move_to_done` 移入 ``done/``
    子目录（文件不可变原则，不再原地修改 status 字段）。
    LLM 不可用时回退到机械判断（无异常 → done）。
    """

    _default_guards = ["actions/pending/action_*.json"]
    _default_produces = ["results/pending/result.json"]

    def __init__(self, node_id: str, host: ApplicationHost, **kwargs: Any) -> None:  # noqa: F821
        super().__init__(node_id, host, system_prompt=_EXECUTE_SYSTEM_PROMPT, **kwargs)
        self._actions_pending_dir = kernel_data_dir / "actions" / "pending"
        self._results_pending_dir = kernel_data_dir / "results" / "pending"

    async def execute(self) -> list[FileUpdate]:
        """扫描 actions/pending/ 中的 action，执行命令并产出结果。

        执行结果写入 ``results/pending/result_<action_id>.json``。
        处理完成的输入 action 通过 :func:`move_to_done` 移入 ``done/``
        子目录（不再原地修改 status 字段，不再跨文件更新 plan）。
        """
        if not self._actions_pending_dir.exists():
            return []

        pending_actions = self._scan_pending_actions()
        if not pending_actions:
            return []

        self._results_pending_dir.mkdir(parents=True, exist_ok=True)
        updates: list[FileUpdate] = []

        for action_path, action_data in pending_actions:
            try:
                command_name = str(action_data.get("command", ""))
                if not command_name:
                    logger.warning(f"action 缺少命令名: {action_path.name}")
                    move_to_done(action_path, action_path.parent / "done")
                    continue

                # 执行命令
                try:
                    result = await self._host.invoke_command(
                        command_name,
                        **self._normalize_kwargs(action_data.get("kwargs")),
                    )
                except Exception as exc:  # noqa: BLE001
                    # 命令执行抛异常 → 直接判定 failed
                    result_data = self._build_result(
                        action_data,
                        status="failed",
                        error=str(exc),
                        result=None,
                    )
                    result_id = str(result_data["id"])
                    updates.append(
                        FileUpdate(
                            descriptor=FileDescriptor(
                                path=f"results/pending/result_{result_id}.json",
                                schema="json",
                            ),
                            content=result_data,
                        )
                    )
                    updates.append(
                        self._build_failure_event(action_data, "failed", str(exc))
                    )
                    logger.warning(f"命令执行异常: {command_name}, error={exc}")
                    self._record_to_memory(action_data, "failed", str(exc))
                    move_to_done(action_path, action_path.parent / "done")
                    continue

                # 让 LLM 判断结果
                judgement = await self._judge_result(action_data, result)
                status = str(judgement.get("status", "done"))

                result_data = self._build_result(
                    action_data,
                    status=status,
                    error=None,
                    result=result,
                    reasoning=str(judgement.get("reasoning", "")),
                    next_step=judgement.get("next_step"),
                )
                result_id = str(result_data["id"])
                updates.append(
                    FileUpdate(
                        descriptor=FileDescriptor(
                            path=f"results/pending/result_{result_id}.json",
                            schema="json",
                        ),
                        content=result_data,
                    )
                )

                logger.info(f"命令执行完成: {command_name} → status={status}")

                if status in ("failed", "retry"):
                    updates.append(
                        self._build_failure_event(
                            action_data,
                            status,
                            reasoning=str(judgement.get("reasoning", "")),
                        )
                    )

                # 记录到记忆
                self._record_to_memory(
                    action_data, status,
                    str(judgement.get("reasoning", "")),
                )

                # 消费输入 action
                move_to_done(action_path, action_path.parent / "done")

            except Exception:
                logger.exception(f"ExecuteAgent 执行 action 失败: {action_path.name}")

        return updates

    async def _judge_result(
        self,
        action_data: dict[str, Any],
        result: Any,
    ) -> dict[str, Any]:
        """调用 LLM 判断执行结果。"""
        action_info = {
            "command": action_data.get("command", ""),
            "kwargs": action_data.get("kwargs", {}),
        }
        user_msg = (
            f"action:\n{json.dumps(action_info, indent=2, ensure_ascii=False)}\n\n"
            f"result:\n{json.dumps(result, indent=2, ensure_ascii=False)}\n\n"
            f"判断执行状态。"
        )
        messages = [{"role": "user", "content": user_msg}]

        try:
            raw = await self.think(messages, max_tokens=256)
        except Exception:
            logger.exception("ExecuteAgent LLM 调用失败，回退到机械判断")
            return self._fallback_judgement(result)

        parsed = parse_llm_json(raw)
        if parsed is None:
            logger.warning(f"ExecuteAgent LLM 输出不可解析，回退到机械判断: {raw!r}")
            return self._fallback_judgement(result)

        return {
            "status": str(parsed.get("status", "done")),
            "reasoning": str(parsed.get("reasoning", "")),
            "next_step": parsed.get("next_step"),
        }

    def _build_result(
        self,
        action_data: dict[str, Any],
        *,
        status: str,
        error: str | None = None,
        result: Any = None,
        reasoning: str = "",
        next_step: Any = None,
    ) -> dict[str, Any]:
        """构造结果文件内容，不再包含 status 字段的原地修改。"""
        timestamp = now_text()
        data: dict[str, Any] = {
            "id": next_record_id("result"),
            "action_id": action_data.get("id", ""),
            "plan_id": action_data.get("plan_id", ""),
            "command": action_data.get("command", ""),
            "judgement": status,
            "reasoning": reasoning,
            "next_step": next_step,
            "result": result,
            "created_at": timestamp,
        }
        if error is not None:
            data["error"] = error
        return data

    @staticmethod
    def _fallback_judgement(result: Any) -> dict[str, Any]:
        """LLM 不可用时的机械判断：检查 result 中的失败标记。

        多数命令返回 ``{"success": true/false, ...}`` 或包含
        ``error`` / ``code`` 字段的 dict。LLM 不可用时用此机械规则兜底，
        不再盲目标记 done。
        """
        if isinstance(result, dict):
            # 显式 success: false → 失败
            if result.get("success") is False:
                return {
                    "status": "failed",
                    "reasoning": "机械判断: result.success=False",
                    "next_step": None,
                }
            # 包含 error / err / code 字段 → 可能失败
            if "error" in result or "err" in result:
                return {
                    "status": "failed",
                    "reasoning": f"机械判断: result 包含错误字段: {result.get('error') or result.get('err')}",
                    "next_step": None,
                }
        if isinstance(result, str) and result.strip():
            lowered = result.lower()
            if any(kw in lowered for kw in ("error", "fail", "失败", "错误")):
                return {
                    "status": "failed",
                    "reasoning": f"机械判断: result 文本包含错误关键词",
                    "next_step": None,
                }
        return {
            "status": "done",
            "reasoning": "LLM 不可用，机械回退未发现失败标记",
            "next_step": None,
        }

    def _scan_pending_actions(
        self,
    ) -> list[tuple[Path, dict[str, Any]]]:
        """扫描 actions/pending/ 目录，返回所有 action 文件。

        文件位置（pending/）即表达状态，不再依赖文件的 status 字段。
        """
        pending: list[tuple[Path, dict[str, Any]]] = []
        for action_path in sorted(self._actions_pending_dir.glob("action_*.json")):
            try:
                data = json.loads(action_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    pending.append((action_path, data))
            except (OSError, json.JSONDecodeError) as exc:
                logger.warning(f"读取 action 文件失败 {action_path.name}: {exc}")
        return pending

    def _record_to_memory(
        self,
        action_data: dict[str, Any],
        status: str,
        detail: str,
    ) -> None:
        """将执行结果写入三级记忆系统。"""
        if self.memory is None:
            return
        session_id = str(action_data.get("session_id", ""))
        if not session_id:
            return
        command = str(action_data.get("command", ""))
        content = f"[{status}] {command}: {detail}"
        self.memory.process_interaction(
            content=content,
            role="system",
            user_id=session_id,
        )

    @staticmethod
    def _normalize_kwargs(value: Any) -> dict[str, Any]:
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _build_failure_event(
        action_data: dict[str, Any],
        status: str,
        reasoning: str,
    ) -> FileUpdate:
        """失败时写回 inbox/pending/，触发 Planner 重规划。"""
        failure_event = {
            "id": next_record_id("event"),
            "type": "exec_failure",
            "source": "executor",
            "session_id": str(action_data.get("session_id", "")),
            "summary": (
                f"命令 {action_data.get('command', '')} 执行{status}: {reasoning}"
            ),
            "payload": {
                "plan_id": action_data.get("plan_id", ""),
                "action_id": action_data.get("id", ""),
                "command": action_data.get("command", ""),
                "kwargs": action_data.get("kwargs", {}),
                "failure_status": status,
                "failure_reasoning": reasoning,
            },
            "created_at": now_text(),
        }
        return FileUpdate(
            descriptor=FileDescriptor(
                path=f"inbox/pending/event_failure_{failure_event['id']}.json",
                schema="json",
            ),
            content=failure_event,
        )

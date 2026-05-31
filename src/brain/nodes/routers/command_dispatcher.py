"""CommandDispatcher —— JSON 解析 → 命令派发 → 历史/记忆写入。

纯机械 Router 节点，零 LLM 调用。读取 ``pipeline/action_queue/*.json``，
解析 LLM 输出的 JSON 动作列表，通过 ApplicationHost 派发命令，
并将结果写入对话历史和统一记忆。

解析失败时写入 inbox 事件自恢复。
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from src.brain.kernel.base import FileDescriptor, FileUpdate, Router
from src.brain.kernel.state_store import kernel_data_dir, move_to_done, next_record_id
from src.utils.json_utils import parse_llm_json, safe_parse_json_object
from src.utils.log_utils import get_logger

if TYPE_CHECKING:
    from src.brain.nodes.pipeline_state import SharedPipelineState
    from src.platform.application_host import ApplicationHost

logger = get_logger("CommandDispatcher")


class CommandDispatcher(Router):
    """命令派发节点。

    读取 action_queue 文件，解析 JSON 动作列表，通过宿主派发命令。
    成功后写入对话历史和统一记忆。解析失败时写入 inbox 事件重试。
    """

    _default_guards = ["pipeline/action_queue/*.json"]  # noqa: RUF012

    def __init__(
        self,
        node_id: str,
        host: "ApplicationHost | None" = None,
        *,
        state: "SharedPipelineState | None" = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(node_id, host=host, **kwargs)
        self._state = state

    async def execute(self) -> list[FileUpdate]:  # noqa: C901, PLR0912, PLR0915
        queue_dir = kernel_data_dir / "pipeline" / "action_queue"
        if not queue_dir.exists():
            return []

        act_files = sorted(queue_dir.glob("act_*.json"), key=lambda p: p.name)
        if not act_files:
            return []

        done_dir = queue_dir / "done"
        done_dir.mkdir(parents=True, exist_ok=True)

        for act_file in act_files:
            try:
                data = json.loads(act_file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                logger.warning("读取 action_queue 失败 %s: %s", act_file.name, exc)
                move_to_done(act_file, done_dir)
                continue
            if not isinstance(data, dict):
                move_to_done(act_file, done_dir)
                continue

            move_to_done(act_file, done_dir)

            user_id = str(data.get("user_id", ""))
            session_key = str(data.get("session_key", ""))
            session_id = str(data.get("session_id", ""))
            merged_input = str(data.get("merged_input", ""))
            is_group = bool(data.get("is_group", False))
            group_id = str(data.get("group_id", "")) if data.get("group_id") else None
            version = int(data.get("version", 0))
            raw_response = str(data.get("raw_response", ""))

            logger.debug("派发动作 session=%s len=%d", session_key, len(raw_response))

            parsed = self._parse_actions(raw_response)
            if parsed is None and raw_response.strip():
                parsed = self._adapt_plain_text(raw_response, user_id, session_id, is_group, group_id)
                if parsed is not None:
                    logger.warning("纯文本兜底发送（JSON 解析失败）session=%s", session_key)

            if parsed is None:
                et = "agent.reply_parse_failed" if raw_response.strip() else "agent.reply_empty"
                summary = "无法解析为结构化动作" if raw_response.strip() else "返回空响应"
                logger.warning("%s session=%s", summary, session_key)
                await self._emit_inbox_event(
                    et,
                    session_key=session_key,
                    merged_input=merged_input,
                    is_group=is_group,
                    group_id=group_id,
                    raw_response=raw_response,
                    version=version,
                )
                continue

            thought = parsed.get("thought", "")
            actions = parsed.get("actions", [])
            if not isinstance(actions, list):
                actions = []

            logger.debug("思考: %s", thought)

            if not actions:
                logger.debug("无动作 session=%s", session_key)
                continue

            # 版本号检查：若会话已产生新版本则放弃过期动作
            if version > 0 and self._state is not None and not self._state.is_version_current(session_key, version):
                logger.debug("版本过期，放弃派发 session=%s", session_key)
                continue

            dispatched = await self._dispatch_actions(actions, session_key, version)
            if dispatched > 0:
                if self._state is not None:
                    await self._state.append_assistant_message(raw_response)
                self._record_unified_memory(raw_response, "assistant", user_id)
                logger.info("回复完成 session=%s user=%s actions=%d", session_key, user_id, dispatched)

        return []

    # ═══════════════════════════════════════════════════
    # JSON 解析
    # ═══════════════════════════════════════════════════

    @staticmethod
    def _parse_actions(raw: str) -> dict[str, Any] | None:
        parsed = parse_llm_json(raw)
        if isinstance(parsed, dict):
            return parsed
        try:
            parsed = safe_parse_json_object(raw)
            if isinstance(parsed, dict):
                return parsed
        except (ValueError, json.JSONDecodeError):
            pass
        return None

    @staticmethod
    def _adapt_plain_text(
        raw: str,
        user_id: str,
        session_id: str,
        is_group: bool,  # noqa: FBT001
        group_id: str | None,
    ) -> dict[str, Any] | None:
        text = raw.strip()
        if not text:
            return None
        if not is_group and session_id == "private:localhost":
            return {
                "thought": text,
                "actions": [
                    {
                        "command": "im.polaris.console.send_message",
                        "params": {"text": text},
                    }
                ],
            }
        if is_group and group_id:
            return {
                "thought": text,
                "actions": [
                    {
                        "command": "im.polaris.qq.send_qq_message",
                        "params": {"session_id": group_id, "text": text},
                    }
                ],
            }
        if session_id and not is_group:
            return {
                "thought": text,
                "actions": [
                    {
                        "command": "im.polaris.qq.send_qq_private_message",
                        "params": {"user_id": user_id, "text": text},
                    }
                ],
            }
        return None

    # ═══════════════════════════════════════════════════
    # 命令派发
    # ═══════════════════════════════════════════════════

    async def _dispatch_actions(
        self,
        actions: list[dict[str, Any]],
        session_key: str,
        version: int,
    ) -> int:
        dispatched = 0
        invalid = 0
        for action in actions:
            if not isinstance(action, dict):
                invalid += 1
                continue
            command = str(action.get("command") or action.get("cmd") or "").strip()
            if not command:
                invalid += 1
                continue
            params = action.get("params", {})
            if not isinstance(params, dict):
                params = {}

            # 版本号检查（逐 action 检查，支持中途过期）
            if version > 0 and self._state is not None and not self._state.is_version_current(session_key, version):
                logger.debug("版本过期，中断派发 session=%s", session_key)
                break

            try:
                if self._host is not None:
                    await self._host.invoke_command(command, **params)
                    dispatched += 1
                else:
                    logger.warning("host 未注入, 无法执行 %s", command)
            except Exception:
                logger.exception("执行命令 %s 失败", command)

        if dispatched == 0 and actions:
            logger.warning(
                "actions 中无可执行命令 session=%s invalid=%d total=%d",
                session_key,
                invalid,
                len(actions),
            )
        return dispatched

    # ═══════════════════════════════════════════════════
    # 统一记忆 & 错误恢复
    # ═══════════════════════════════════════════════════

    @staticmethod
    def _record_unified_memory(content: str, role: str, user_id: str) -> None:
        try:
            from src.brain.memory import memory_manager

            memory_manager.process_interaction(content=content, role=role, user_id=str(user_id))
        except Exception:
            logger.exception("写入统一记忆失败 (%s)", role)

    async def _emit_inbox_event(  # noqa: PLR0913
        self,
        event_type: str,
        *,
        session_key: str,
        merged_input: str,
        is_group: bool,
        group_id: str | None,
        raw_response: str,
        version: int,
    ) -> None:
        safe_type = str(event_type).replace(".", "_").replace("/", "_")
        event_id = next_record_id("evt")
        relative_path = f"inbox/pending/event_{safe_type}_{event_id}.json"

        event = {
            "source": self.id,
            "type": event_type,
            "session_id": "",
            "summary": "无法解析为结构化动作" if raw_response.strip() else "返回空响应",
            "payload": {
                "session_key": session_key,
                "merged_input": merged_input,
                "is_group": is_group,
                "group_id": group_id,
                "raw_response": raw_response,
                "version": version,
            },
            "expire_at": None,
            "id": event_id,
        }

        update = FileUpdate(
            descriptor=FileDescriptor(path=relative_path, schema="json"),
            content=event,
        )
        if self._bus is not None:
            await self._bus.apply_update(update, self.id)
        else:
            logger.warning("事件总线未注入，无法写入错误事件")
        logger.info("已写入 inbox 事件 %s", relative_path)

"""kernel-α: AuroraBot PolarisAgent —— 小光的自主认知节点

Pipeline: 事件收束 → 格式化为文本 → 门控判断 → LLM 动作规划 → 命令派发

设计哲学：
- 所有事件一律格式化为自然语言文本，代码层不做事件类型分叉。
- LLM 输出统一为 JSON 动作列表，解析失败写入 inbox 自恢复。
- SOUL 人格注入对话历史，动作规划阶段去人格化（严格 JSON）。
"""

from __future__ import annotations

import asyncio
import json
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta
from typing import Any, TYPE_CHECKING

from src.brain.ai.llm_gate import llm_chat
from src.brain.kernel.base import Agent, FileDescriptor, FileUpdate
from src.brain.kernel.state_store import kernel_data_dir, move_to_done, next_record_id
from src.config import Config
from src.utils.log_utils import get_logger
from src.utils.time_utils import now_text
from src.utils.json_utils import parse_llm_json, safe_parse_json_object

import src.brain.prompts as prompts

if TYPE_CHECKING:
    from src.platform.application_host import ApplicationHost

logger = get_logger("PolarisAgent")

REPLY_DEBOUNCE_SECONDS = 2.0
RECENT_MESSAGE_LIMIT = 6
MESSAGE_WINDOW = 300
ACTION_WINDOW = 50
MAX_SELF_RECOVERY_ATTEMPTS = 2


class PolarisAgent(Agent):
    """小光的自主认知节点。

    守护 inbox 中所有 event_*.json 事件，
    统一经过「格式化 → 门控 → 动作规划 → 命令派发」流水线。
    """

    _default_guards = ["inbox/pending/event_*.json"]

    def __init__(
        self,
        node_id: str,
        host: ApplicationHost | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(node_id, host=host, **kwargs)

        self._history_path = Config.DATA_DIR / "history.json"
        self._soul = ""
        self._history_lock = asyncio.Lock()
        self._session_versions: dict[str, int] = {}
        self._pending_inputs: dict[str, list[dict[str, Any]]] = {}
        self._group_recent: dict[int, deque[tuple[float, str]]] = defaultdict(
            lambda: deque()
        )
        self._private_recent: dict[str, deque[tuple[float, str]]] = defaultdict(
            lambda: deque()
        )
        self._init_data()

    # ═══════════════════════════════════════════════════
    # 生命周期
    # ═══════════════════════════════════════════════════

    def _init_data(self) -> None:
        self._soul = prompts.SOUL.get_content()
        self._history_path.parent.mkdir(parents=True, exist_ok=True)
        is_empty = False
        if self._history_path.exists():
            content = self._history_path.read_text(encoding="utf-8").strip()
            if not content:
                is_empty = True
            else:
                try:
                    history = json.loads(content)
                    is_empty = history == []
                except json.JSONDecodeError:
                    logger.error("history.json 格式错误，将重新初始化")
                    is_empty = True
        else:
            is_empty = True
        if is_empty:
            self._history_path.write_text(
                json.dumps(
                    [{"role": "system", "content": self._soul}],
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

    async def run(self) -> None:
        await super().run()

    # ═══════════════════════════════════════════════════
    # execute —— 事件收束 & 统一入口
    # ═══════════════════════════════════════════════════

    async def execute(self) -> list[FileUpdate]:
        pending_dir = kernel_data_dir / "inbox" / "pending"
        if not pending_dir.exists():
            return []

        event_files = sorted(
            pending_dir.glob("event_*.json"),
            key=lambda p: p.name,
        )
        if not event_files:
            return []

        done_dir = pending_dir / "done"
        done_dir.mkdir(parents=True, exist_ok=True)

        for event_file in event_files:
            try:
                data = json.loads(event_file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                logger.warning("读取事件失败 %s: %s", event_file.name, exc)
                move_to_done(event_file, done_dir)
                continue
            if not isinstance(data, dict):
                move_to_done(event_file, done_dir)
                continue

            move_to_done(event_file, done_dir)

            event_type = str(data.get("type", ""))
            input_text = self._format_event_as_text(data)

            if not input_text:
                continue

            if event_type == "message.received":
                self._enqueue_message(data, input_text)
            else:
                asyncio.create_task(self._process_system_event(event_type, input_text))

        return []

    # ═══════════════════════════════════════════════════
    # 事件 → 自然语言文本（代码层不做类型分叉）
    # ═══════════════════════════════════════════════════

    @staticmethod
    def _format_event_as_text(data: dict[str, Any]) -> str:
        event_type = str(data.get("type", ""))
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        summary = str(data.get("summary", "")).strip()
        payload = (
            data.get("payload", {}) if isinstance(data.get("payload"), dict) else {}
        )

        if event_type == "message.received":
            user_id = str(payload.get("user_id", ""))
            text = str(payload.get("text", "")).strip()
            if not text:
                return ""
            is_group = bool(payload.get("is_group", False))
            group_id = str(payload.get("group_id", "")) if is_group else None
            if is_group and group_id:
                return f"{timestamp} 的时候, {user_id} 在群聊 {group_id} 中说: {text}"
            return f"{timestamp} 的时候, {user_id} 在与你的私聊中说: {text}"

        parts = [f"[系统事件] {timestamp} {event_type}"]
        if summary:
            parts.append(f"摘要: {summary}")
        if payload:
            parts.append(f"详情: {json.dumps(payload, ensure_ascii=False)}")
        return "\n".join(parts)

    # ═══════════════════════════════════════════════════
    # 消息入队 → 防抖 → 门控 → 流水线
    # ═══════════════════════════════════════════════════

    def _enqueue_message(self, data: dict[str, Any], input_text: str) -> None:
        payload = (
            data.get("payload", {}) if isinstance(data.get("payload"), dict) else {}
        )
        user_id = str(payload.get("user_id", ""))
        session_id = str(payload.get("session_id", ""))
        is_group = bool(payload.get("is_group", False))
        group_id = str(payload.get("group_id", "")) if is_group else None
        session_key = self._make_session_key(user_id, is_group, group_id)

        logger.info(
            "收到消息 session=%s user=%s text=%.60s",
            session_key,
            user_id,
            input_text,
        )

        scene_name = "群聊" if is_group else "私聊"
        if is_group:
            self._append_recent_message(
                self._group_recent[int(group_id or 0)], input_text
            )
        else:
            self._append_recent_message(self._private_recent[user_id], input_text)

        entry = {
            "user_id": user_id,
            "session_key": session_key,
            "session_id": session_id,
            "input_text": input_text,
            "is_group": is_group,
            "group_id": group_id,
            "scene_name": scene_name,
        }
        self._pending_inputs.setdefault(session_key, []).append(entry)
        version = self._session_versions.get(session_key, 0) + 1
        self._session_versions[session_key] = version
        asyncio.create_task(self._debounce_and_reply(session_key, version))

    # ═══════════════════════════════════════════════════
    # 系统事件（clock / agent.reply 等）→ 跳过门控
    # ═══════════════════════════════════════════════════

    async def _process_system_event(self, event_type: str, input_text: str) -> None:
        logger.info("处理系统事件 type=%s text=%s", event_type, input_text)
        recovery_note = ""
        if event_type.startswith("agent.reply_"):
            recovery_note = (
                "你上一轮的输出不是有效 JSON。现在重新输出，必须只给 JSON 对象。"
            )
        await self._run_reply_pipeline(
            user_id="system",
            session_key=f"system:{event_type}",
            session_id="",
            merged_input=input_text,
            is_group=False,
            group_id=None,
            version=0,
            append_user=False,
            recovery_depth=0,
            recovery_note=recovery_note,
        )

    # ═══════════════════════════════════════════════════
    # 防抖
    # ═══════════════════════════════════════════════════

    async def _debounce_and_reply(self, session_key: str, version: int) -> None:
        await asyncio.sleep(REPLY_DEBOUNCE_SECONDS)

        if self._session_versions.get(session_key) != version:
            return

        entries = self._pending_inputs.pop(session_key, [])
        if not entries:
            return

        merged_input = "\n".join(e["input_text"] for e in entries)
        first = entries[0]
        user_id = first["user_id"]
        session_id = first["session_id"]
        is_group = first["is_group"]
        group_id = first["group_id"]
        scene_name = first["scene_name"]

        logger.info(
            "防抖完成 session=%s 合并 %d 条 → 门控",
            session_key,
            len(entries),
        )

        recent = (
            self._group_recent[int(group_id or 0)]
            if is_group
            else self._private_recent[user_id]
        )
        recent_lines = self._get_recent_lines(recent)

        try:
            should_reply = await self._impulse_gate(
                scene_name, recent_lines, merged_input
            )
        except Exception:
            logger.exception("门控异常，跳过")
            return

        if not should_reply:
            logger.info("门控判定不回复 session=%s", session_key)
            return

        logger.info("门控通过 → 动作规划")
        await self._run_reply_pipeline(
            user_id=user_id,
            session_key=session_key,
            session_id=session_id,
            merged_input=merged_input,
            is_group=is_group,
            group_id=group_id,
            version=version,
            append_user=True,
            recovery_depth=0,
        )

    # ═══════════════════════════════════════════════════
    # 脉冲门控
    # ═══════════════════════════════════════════════════

    async def _impulse_gate(
        self,
        scene_name: str,
        recent_lines: list[str],
        merged_input: str,
    ) -> bool:
        recent_text = "\n".join(recent_lines) if recent_lines else "(暂无历史)"
        messages = [
            {"role": "system", "content": prompts.GATE.get_content()},
            {
                "role": "user",
                "content": prompts.GATE_USER.fill(
                    soul=self._soul,
                    scene_name=scene_name,
                    recent_limit=str(RECENT_MESSAGE_LIMIT),
                    recent_text=recent_text,
                    merged_input=merged_input,
                ),
            },
        ]
        try:
            response = await llm_chat(messages, max_tokens=512, temperature=0.0)
        except Exception:
            logger.exception("门控 LLM 调用失败，默认不回复")
            return False
        if not response or not response.strip():
            logger.warning("门控返回空，默认不回复")
            return False
        return self._parse_yes_no(response)

    @staticmethod
    def _parse_yes_no(text: str) -> bool:
        content = (text or "").strip()
        if content in ("是", "否"):
            return content == "是"
        if "是" in content:
            return True
        return False

    # ═══════════════════════════════════════════════════
    # 回复流水线：LLM 生成 → JSON 解析 → 命令派发
    # ═══════════════════════════════════════════════════

    async def _run_reply_pipeline(
        self,
        *,
        user_id: str,
        session_key: str,
        session_id: str,
        merged_input: str,
        is_group: bool,
        group_id: str | None,
        version: int,
        append_user: bool,
        recovery_depth: int,
        recovery_note: str = "",
    ) -> None:
        try:
            raw = await self._generate_actions(
                user_id=user_id,
                merged_input=merged_input,
                session_id=session_id,
                is_group=is_group,
                group_id=group_id,
                append_user=append_user,
                recovery_note=recovery_note,
            )
        except Exception:
            logger.exception("LLM 动作生成失败")
            await self._emit_inbox_event(
                "agent.reply_generation_failed",
                session_id=session_id,
                summary="LLM 动作生成失败",
                payload={
                    "session_key": session_key,
                    "merged_input": merged_input,
                    "is_group": is_group,
                    "group_id": group_id,
                    "version": version,
                    "recovery_depth": recovery_depth,
                },
            )
            return

        logger.info("动作生成完成 len=%d preview=%.80s", len(raw), raw)

        parsed = self._parse_actions(raw)
        if parsed is None:
            if raw.strip() and recovery_depth == 0:
                parsed = self._adapt_plain_text(
                    raw, user_id, session_id, is_group, group_id
                )
                if parsed is not None:
                    logger.warning(
                        "纯文本兜底发送（JSON 解析失败）session=%s", session_key
                    )
        if parsed is None:
            et = "agent.reply_parse_failed" if raw.strip() else "agent.reply_empty"
            summary = "无法解析为结构化动作" if raw.strip() else "返回空响应"
            logger.warning("%s session=%s", summary, session_key)
            await self._emit_inbox_event(
                et,
                session_id=session_id,
                summary=summary,
                payload={
                    "session_key": session_key,
                    "merged_input": merged_input,
                    "is_group": is_group,
                    "group_id": group_id,
                    "raw_response": raw,
                    "version": version,
                    "recovery_depth": recovery_depth,
                },
            )
            return

        thought = parsed.get("thought", "")
        actions = parsed.get("actions", [])
        if not isinstance(actions, list):
            actions = []

        logger.info("思考: %.120s", thought)

        if not actions:
            logger.info("无动作 session=%s", session_key)
            return

        if version > 0 and self._session_versions.get(session_key) != version:
            return

        dispatched = await self._dispatch_actions(actions, session_key, version)
        if dispatched > 0:
            await self._append_assistant_message(raw)
            logger.info(
                "回复完成 session=%s user=%s actions=%d",
                session_key,
                user_id,
                dispatched,
            )

    # ═══════════════════════════════════════════════════
    # LLM 动作生成
    # ═══════════════════════════════════════════════════

    async def _generate_actions(
        self,
        *,
        user_id: str,
        merged_input: str,
        session_id: str,
        is_group: bool,
        group_id: str | None,
        append_user: bool,
        recovery_note: str = "",
    ) -> str:
        if append_user:
            messages = await self._append_user_message(user_id, merged_input)
        else:
            messages = await self._get_recent_history_messages()
            if not messages or messages[-1].get("role") != "user":
                messages.append(
                    {
                        "role": "user",
                        "name": str(user_id),
                        "content": merged_input,
                    }
                )

        if messages and messages[0].get("role") == "system":
            messages = messages[1:]

        messages = self._trim_for_action(messages)

        scene_text = self._build_scene_text(session_id, is_group, group_id)
        commands_text = self._build_commands_text()
        memory_text = self._build_memory_text(user_id)
        action_prompt = prompts.ACTION.fill(
            scene=scene_text,
            commands=commands_text,
        )

        final_instruction = (
            f"{action_prompt}\n\n"
            "（只输出 JSON。第一个字符 {，最后一个 }。不要任何其他文字。）"
        )
        if recovery_note:
            final_instruction = f"{recovery_note}\n\n{final_instruction}"

        messages.append({"role": "user", "content": final_instruction})

        response = await llm_chat(
            [{"role": "system", "content": memory_text}] + messages,
            max_tokens=2048,
            temperature=0.0,
        )
        return (response or "").strip()

    # ═══════════════════════════════════════════════════
    # 场景 & 命令 & 记忆 上下文构建
    # ═══════════════════════════════════════════════════

    @staticmethod
    def _build_scene_text(
        session_id: str,
        is_group: bool,
        group_id: str | None,
    ) -> str:
        stype = "群聊" if is_group else "私聊"
        gid = group_id or "无"
        return f"会话类型: {stype}\n" f"会话 ID: {session_id}\n" f"群号: {gid}"

    def _build_commands_text(self) -> str:
        if self._host is None:
            return "无可用命令"
        lines: list[str] = []
        for spec in self._host.list_command_specs():
            params = spec.parameters_schema.get("properties", {})
            required = spec.parameters_schema.get("required", [])
            param_entries = []
            example_params = {}
            for pname, pschema in params.items():
                req_mark = " (必填)" if pname in required else ""
                param_entries.append(
                    f"    {pname}: {pschema.get('type', 'string')}{req_mark} — {pschema.get('description', '')}"
                )
                example_params[pname] = f"<{pschema.get('type', 'string')}>"
            example_json = json.dumps(
                {"command": spec.name, "params": example_params},
                ensure_ascii=False,
            )
            lines.append(f"## {spec.name}")
            lines.append(f"  {spec.description}")
            lines.append("  参数:")
            lines.extend(param_entries)
            lines.append(f"  示例: {example_json}")
            lines.append("")
        return "\n".join(lines)

    def _build_memory_text(self, current_user_id: str) -> str:
        diaries = self._load_previous_two_diaries()
        impressions = self._load_all_impressions()
        prioritized = self._prioritize_impressions(current_user_id, impressions)

        diary_lines = [f"## {d['date']}\n{d['content']}" for d in diaries]
        diary_block = "\n".join(diary_lines) if diary_lines else "无"

        impression_block = (
            json.dumps(prioritized, ensure_ascii=False, indent=2)
            if prioritized
            else "{}"
        )
        return prompts.MEMORY.fill(
            diary_block=diary_block,
            impression_block=impression_block,
        )

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
        is_group: bool,
        group_id: str | None,
    ) -> dict[str, Any] | None:
        text = raw.strip()
        if not text:
            return None
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

    @staticmethod
    def _trim_for_action(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        recent_start = max(1, len(messages) - ACTION_WINDOW)
        return messages[recent_start:]

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

            if version > 0 and self._session_versions.get(session_key) != version:
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
    # 对话历史
    # ═══════════════════════════════════════════════════

    async def _append_user_message(
        self, user_id: str, input_line: str
    ) -> list[dict[str, Any]]:
        async with self._history_lock:
            history = self._read_history()
            if (
                history
                and history[-1].get("role") == "user"
                and history[-1].get("name") == str(user_id)
            ):
                prev = history[-1].get("content", "")
                history[-1]["content"] = f"{prev}\n{input_line}" if prev else input_line
            else:
                history.append(
                    {
                        "role": "user",
                        "name": str(user_id),
                        "content": input_line,
                    }
                )
            self._write_history(history)
            recent_start = max(1, len(history) - MESSAGE_WINDOW)
            return history[:1] + history[recent_start:]

    async def _append_assistant_message(self, content: str) -> None:
        async with self._history_lock:
            history = self._read_history()
            history.append({"role": "assistant", "content": content})
            self._write_history(history)

    async def _get_recent_history_messages(self) -> list[dict[str, Any]]:
        async with self._history_lock:
            history = self._read_history()
            recent_start = max(1, len(history) - MESSAGE_WINDOW)
            return history[:1] + history[recent_start:]

    def _read_history(self) -> list[dict[str, Any]]:
        try:
            if self._history_path.exists():
                content = self._history_path.read_text(encoding="utf-8").strip()
                if content:
                    data = json.loads(content)
                    if isinstance(data, list):
                        return data
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("读取 history.json 失败: %s", exc)
        return [{"role": "system", "content": self._soul}]

    def _write_history(self, history: list[dict[str, Any]]) -> None:
        self._history_path.parent.mkdir(parents=True, exist_ok=True)
        self._history_path.write_text(
            json.dumps(history, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    # ═══════════════════════════════════════════════════
    # inbox 错误事件
    # ═══════════════════════════════════════════════════

    async def _emit_inbox_event(
        self,
        event_type: str,
        *,
        session_id: str = "",
        summary: str = "",
        payload: dict[str, Any] | None = None,
    ) -> str:
        safe_type = str(event_type).replace(".", "_").replace("/", "_")
        event_id = next_record_id("evt")
        relative_path = f"inbox/pending/event_{safe_type}_{event_id}.json"
        event = {
            "source": self.id,
            "type": event_type,
            "session_id": session_id,
            "summary": summary,
            "payload": payload or {},
            "expire_at": None,
            "id": event_id,
            "created_at": now_text(),
        }
        update = FileUpdate(
            descriptor=FileDescriptor(path=relative_path, schema="json"),
            content=event,
        )
        if self._bus is not None:
            await self._bus.apply_update(update, self.id)
        else:
            event_path = kernel_data_dir / relative_path
            event_path.parent.mkdir(parents=True, exist_ok=True)
            event_path.write_text(
                json.dumps(event, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        logger.info("已写入 inbox 事件 %s", relative_path)
        return relative_path

    # ═══════════════════════════════════════════════════
    # 日记 & 印象记忆
    # ═══════════════════════════════════════════════════

    def _load_previous_two_diaries(self) -> list[dict[str, str]]:
        diary_dir = Config.DATA_DIR / "app_data" / "im_polaris_diary" / "diaries"
        diaries: list[dict[str, str]] = []
        for days_ago in (1, 2):
            target = (datetime.now() - timedelta(days=days_ago)).strftime("%Y-%m-%d")
            path = diary_dir / f"{target}.json"
            if path.exists():
                try:
                    diaries.append(
                        {"date": target, "content": path.read_text(encoding="utf-8")}
                    )
                except OSError:
                    pass
        return diaries

    def _load_all_impressions(self) -> dict[str, Any]:
        impression_dir = Config.DATA_DIR / "impressions"
        payload: dict[str, Any] = {}
        if not impression_dir.exists():
            return payload
        for path in sorted(impression_dir.glob("*.json")):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    payload[path.stem] = json.load(f)
            except Exception:
                continue
        return payload

    @staticmethod
    def _prioritize_impressions(
        current_user_id: str,
        impressions: dict[str, Any],
    ) -> dict[str, Any]:
        if not impressions:
            return {}
        user_key = str(current_user_id)
        related: set[str] = set()
        cur = impressions.get(user_key) or {}
        for row in cur.get("relationships", []):
            if isinstance(row, dict):
                t = str(row.get("target_user_id", "")).strip()
                if t:
                    related.add(t)
        for cid, p in impressions.items():
            for row in p.get("relationships", []):
                if (
                    isinstance(row, dict)
                    and str(row.get("target_user_id", "")).strip() == user_key
                ):
                    related.add(str(cid))
        ordered: list[str] = []
        if user_key in impressions:
            ordered.append(user_key)
        ordered.extend(
            uid for uid in sorted(related) if uid in impressions and uid != user_key
        )
        ordered.extend(uid for uid in sorted(impressions) if uid not in ordered)
        return {uid: impressions[uid] for uid in ordered}

    # ═══════════════════════════════════════════════════
    # 滑动窗口 & 小工具
    # ═══════════════════════════════════════════════════

    @staticmethod
    def _recent_window_seconds() -> float:
        return float(RECENT_MESSAGE_LIMIT) * 60.0

    def _prune_recent_messages(
        self,
        recent: deque[tuple[float, str]],
        now_ts: float | None = None,
    ) -> None:
        now = time.time() if now_ts is None else now_ts
        cutoff = now - self._recent_window_seconds()
        while recent and recent[0][0] < cutoff:
            recent.popleft()

    def _append_recent_message(
        self,
        recent: deque[tuple[float, str]],
        msg: str,
    ) -> None:
        self._prune_recent_messages(recent, now_ts := time.time())
        recent.append((now_ts, msg))

    def _get_recent_lines(self, recent: deque[tuple[float, str]]) -> list[str]:
        self._prune_recent_messages(recent)
        return [line for _, line in recent]

    @staticmethod
    def _make_session_key(user_id: str, is_group: bool, group_id: str | None) -> str:
        return f"group:{group_id}:{user_id}" if is_group else f"private:{user_id}"

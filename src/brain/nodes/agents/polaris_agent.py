"""kernel-α: AuroraBot PolarisAgent 单体节点

移植自 XiaoGuang-Bot/polaris/main.py + polaris/tasks/diary.py，
"""

from __future__ import annotations

import asyncio
import json
import time
from collections import defaultdict, deque
from datetime import date, datetime, timedelta
from typing import Any, TYPE_CHECKING

from src.brain.ai.llm_gate import llm_chat
from src.brain.kernel.base import Agent, FileDescriptor, FileUpdate
from src.brain.kernel.state_store import kernel_data_dir, move_to_done, next_record_id
from src.config import Config
from src.utils.log_utils import get_logger
from src.utils.time_utils import now_text
from src.utils.json_utils import safe_parse_json_object

import src.brain.prompts as prompts

if TYPE_CHECKING:
    from src.platform.application_host import ApplicationHost

logger = get_logger("PolarisAgent")

# ═══════════════════════════════════════════════════════════════
# 常量
# ═══════════════════════════════════════════════════════════════

REPLY_DEBOUNCE_SECONDS = 2.0
RECENT_MESSAGE_LIMIT = 6  # 分钟
MESSAGE_WINDOW = 300
MAX_SELF_RECOVERY_ATTEMPTS = 2

# 脉冲门控系统提示词
IMPULSE_GATE_PROMPT = prompts.IMPULSE_GATE.get_content()


# ═══════════════════════════════════════════════════════════════
# PolarisAgent
# ═══════════════════════════════════════════════════════════════


class PolarisAgent(Agent):
    """kernel-α:　AuroraBot PolarisAgent

    守护消息事件和自身回复失败事件，
    处理流程包括：防抖合并 → 脉冲门控 → LLM 回复 → 命令派发
    与失败后的自恢复重试。

    内部维护：
    - history.json 对话历史（asyncio.Lock 保护）
    - 最近消息滑动窗口（按群/私聊分组）
    - 会话版本号（防抖用）
    """

    _default_guards = ["inbox/pending/event_*.json"]

    def __init__(
        self,
        node_id: str,
        host: ApplicationHost | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(node_id, host=host, **kwargs)

        # ── 数据路径（保留 XiaoGuang-Bot 原始目录结构） ──
        self._history_path = Config.DATA_DIR / "history.json"
        self._soul_path = Config.PROMPTS_DIR / "SOUL.md"

        # ── 运行时状态 ──
        self._history_lock = asyncio.Lock()
        self._session_versions: dict[str, int] = {}
        self._pending_inputs: dict[str, list[dict[str, Any]]] = {}
        self._group_recent: dict[int, deque[tuple[float, str]]] = defaultdict(
            lambda: deque()
        )
        self._private_recent: dict[str, deque[tuple[float, str]]] = defaultdict(
            lambda: deque()
        )

        # ── SOUL ──
        self._soul = ""
        self._init_data()

    # ── 生命周期 ──────────────────────────────────────

    def _init_data(self) -> None:
        """初始化 SOUL 与 history.json。"""
        # 加载 SOUL
        self._soul = prompts.SOUL.get_content()

        # 初始化 history.json（空则写入 system 消息）
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
            history = [{"role": "system", "content": self._soul}]
            self._history_path.write_text(
                json.dumps(history, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    async def run(self) -> None:
        """启动节点主循环。"""
        await super().run()

    # ── execute ───────────────────────────────────────

    async def execute(self) -> list[FileUpdate]:
        """扫描待处理事件，启动回复流水线或自恢复流程。

        处理完成的输入文件移入 done/ 子目录。
        本方法快速返回（仅 spawn 后台任务），不阻塞事件循环。
        """
        pending_dir = kernel_data_dir / "inbox" / "pending"
        if not pending_dir.exists():
            return []

        event_files = sorted(
            pending_dir.glob("event_*.json"),
            key=lambda path: path.name,
        )
        if not event_files:
            return []

        done_dir = pending_dir / "done"
        done_dir.mkdir(parents=True, exist_ok=True)

        for event_file in event_files:
            try:
                data = json.loads(event_file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                logger.warning("PolarisAgent 读取事件失败 %s: %s", event_file.name, exc)
                move_to_done(event_file, done_dir)
                continue

            if not isinstance(data, dict):
                move_to_done(event_file, done_dir)
                continue

            event_type = str(data.get("type", "")).strip()
            payload = data.get("payload", {})
            if not isinstance(payload, dict):
                logger.warning("PolarisAgent: 事件 payload 无效 %s", event_file.name)
                move_to_done(event_file, done_dir)
                continue

            move_to_done(event_file, done_dir)

            if event_type == "message.received":
                self._queue_message_event(payload)
                continue

            if event_type.startswith("agent.reply_"):
                asyncio.create_task(
                    self._consume_reply_failure_event(
                        event_type=event_type,
                        session_id=str(data.get("session_id", "")),
                        summary=str(data.get("summary", "")),
                        payload=payload,
                    )
                )
                continue

            if event_type.startswith("clock."):
                asyncio.create_task(
                    self._consume_clock_event(
                        event_type=event_type,
                        summary=str(data.get("summary", "")),
                        payload=payload,
                    )
                )
                continue

            logger.debug(
                "PolarisAgent: 忽略未处理事件 %s (%s)", event_file.name, event_type
            )

        return []

    def _queue_message_event(self, payload: dict[str, Any]) -> None:
        text = str(payload.get("text", "")).strip()
        if not text:
            return

        user_id = str(payload.get("user_id", ""))
        session_id = str(payload.get("session_id", ""))
        is_group = bool(payload.get("is_group", False))
        group_id = str(payload.get("group_id", "")) if is_group else None
        session_key = self._make_session_key(user_id, is_group, group_id)

        logger.info(
            "PolarisAgent: 收到消息 session=%s user=%s is_group=%s text=%.60s",
            session_key,
            user_id,
            is_group,
            text,
        )

        timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        if is_group and group_id:
            input_line = f"{timestamp} 的时候, {user_id} 在群聊 {group_id} 中说: {text}"
            scene_name = "群聊"
        else:
            input_line = f"{timestamp} 的时候, {user_id} 在与你的私聊中说: {text}"
            scene_name = "私聊"

        if is_group:
            self._append_recent_message(
                self._group_recent[int(group_id or 0)], input_line
            )
        else:
            self._append_recent_message(self._private_recent[user_id], input_line)

        entry = {
            "user_id": user_id,
            "session_key": session_key,
            "session_id": session_id,
            "input_line": input_line,
            "text": text,
            "is_group": is_group,
            "group_id": group_id,
            "scene_name": scene_name,
        }
        self._pending_inputs.setdefault(session_key, []).append(entry)
        current_version = self._session_versions.get(session_key, 0) + 1
        self._session_versions[session_key] = current_version
        asyncio.create_task(self._debounce_and_reply(session_key, current_version))

    async def _consume_reply_failure_event(
        self,
        *,
        event_type: str,
        session_id: str,
        summary: str,
        payload: dict[str, Any],
    ) -> None:
        scene_info = payload.get("scene_info", {})
        if not isinstance(scene_info, dict):
            logger.warning("PolarisAgent: 回复失败事件缺少 scene_info")
            return

        merged_input = str(payload.get("merged_input", "")).strip()
        if not merged_input:
            logger.warning("PolarisAgent: 回复失败事件缺少 merged_input")
            return

        user_id = str(scene_info.get("user_id", "")).strip()
        if not user_id:
            logger.warning("PolarisAgent: 回复失败事件缺少 user_id")
            return

        is_group = bool(scene_info.get("is_group", False))
        group_id = str(scene_info.get("group_id", "")) if is_group else None
        session_key = str(
            payload.get("session_key", "")
        ).strip() or self._make_session_key(
            user_id,
            is_group,
            group_id,
        )
        event_session_id = session_id or str(scene_info.get("session_id", ""))
        recovery_depth = self._coerce_int(payload.get("recovery_depth"), default=0)
        if recovery_depth >= MAX_SELF_RECOVERY_ATTEMPTS:
            logger.warning(
                "PolarisAgent: 自恢复次数已达上限，放弃继续恢复 session=%s type=%s",
                session_key,
                event_type,
            )
            return

        expected_version = self._coerce_int(payload.get("version"), default=0)
        current_version = self._session_versions.get(session_key)
        if (
            expected_version > 0
            and current_version is not None
            and current_version != expected_version
        ):
            logger.info(
                "PolarisAgent: 回复失败事件已过期，跳过恢复 session=%s expected=%s current=%s",
                session_key,
                expected_version,
                current_version,
            )
            return

        logger.info(
            "PolarisAgent: 自恢复回复失败事件 session=%s type=%s depth=%d",
            session_key,
            event_type,
            recovery_depth + 1,
        )
        await self._run_reply_pipeline(
            user_id=user_id,
            session_key=session_key,
            session_id=event_session_id,
            merged_input=merged_input,
            scene_info=scene_info,
            version=expected_version,
            append_user=False,
            recovery_depth=recovery_depth + 1,
            recovery_note=self._build_recovery_note(event_type, summary, payload),
        )

    async def _consume_clock_event(
        self,
        *,
        event_type: str,
        summary: str,
        payload: dict[str, Any],
    ) -> None:
        kind = str(payload.get("kind", ""))
        message = str(payload.get("message", summary)).strip()
        kind_label = "闹钟" if kind == "alarm" else "计时器"

        synthetic_input = f"[系统通知] 你的{kind_label}响了: {message}"

        logger.info(
            "PolarisAgent: 收到时钟事件 %s message=%s",
            event_type,
            message,
        )

        scene_info: dict[str, Any] = {
            "session_id": "",
            "is_group": False,
            "group_id": None,
            "user_id": "system",
            "scene_name": "系统通知",
        }
        await self._run_reply_pipeline(
            user_id="system",
            session_key="system:clock",
            session_id="",
            merged_input=synthetic_input,
            scene_info=scene_info,
            version=0,
            append_user=False,
            recovery_depth=0,
        )

    # ── 防抖与回复 ────────────────────────────────────

    async def _debounce_and_reply(self, session_key: str, version: int) -> None:
        """等待防抖窗口后，若版本未变则合并输入并处理。"""
        await asyncio.sleep(REPLY_DEBOUNCE_SECONDS)

        if self._session_versions.get(session_key) != version:
            logger.debug("PolarisAgent: 防抖被新消息打断 (session=%s)", session_key)
            return  # 新消息已到达，由它接管

        entries = self._pending_inputs.pop(session_key, [])
        if not entries:
            return

        # 合并为单条用户输入
        merged_input = "\n".join(entry["input_line"] for entry in entries)
        user_id = entries[0]["user_id"]
        session_id = entries[0]["session_id"]
        is_group = entries[0]["is_group"]
        group_id = entries[0]["group_id"]
        scene_name = entries[0]["scene_name"]

        logger.info(
            "PolarisAgent: 防抖完成 session=%s 合并 %d 条 → 脉冲门控",
            session_key,
            len(entries),
        )

        # ── 脉冲门控 ──
        recent_messages = (
            self._group_recent[int(group_id or 0)]
            if is_group
            else self._private_recent[user_id]
        )
        recent_lines = self._get_recent_lines(recent_messages)

        try:
            should_reply = await self._impulse_gate(
                scene_name, recent_lines, merged_input
            )
        except Exception:
            logger.exception("PolarisAgent 脉冲门控异常，默认跳过回复")
            return

        if not should_reply:
            logger.info("PolarisAgent: 脉冲门控判定不回复 (session=%s)", session_key)
            return

        logger.info("PolarisAgent: 脉冲门控通过 → LLM 回复生成")

        # ── 构建场景信息 ──
        scene_info: dict[str, Any] = {
            "session_id": session_id,
            "is_group": is_group,
            "group_id": group_id,
            "user_id": user_id,
            "scene_name": scene_name,
        }

        await self._run_reply_pipeline(
            user_id=user_id,
            session_key=session_key,
            session_id=session_id,
            merged_input=merged_input,
            scene_info=scene_info,
            version=version,
            append_user=True,
            recovery_depth=0,
        )

    # ── 脉冲门控 ──────────────────────────────────────

    async def _impulse_gate(
        self,
        scene_name: str,
        recent_lines: list[str],
        merged_input: str,
    ) -> bool:
        """调用 LLM 判断当前是否应该回复。"""
        recent_text = "\n".join(recent_lines) if recent_lines else "(暂无历史)"

        messages = [
            {"role": "system", "content": IMPULSE_GATE_PROMPT},
            {
                "role": "user",
                "content": prompts.IMPULSE_GATE_USER.fill(
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
            logger.exception("PolarisAgent 脉冲门控 LLM 调用失败，默认不回复")
            return False

        # 空响应兜底：模型返回空时默认不回复（避免无节制搭话）
        if not response or not response.strip():
            logger.warning("PolarisAgent: 脉冲门控 LLM 返回空响应，默认不回复")
            return False

        return self._parse_yes_no(response)

    @staticmethod
    def _parse_yes_no(text: str) -> bool:
        content = (text or "").strip()
        if content == "是":
            return True
        if content == "否":
            return False
        if '"reply":"是"' in content or '"reply": "是"' in content:
            return True
        if "是" in content:
            return True
        return False

    # ── LLM 回复生成 ──────────────────────────────────

    async def _run_reply_pipeline(
        self,
        *,
        user_id: str,
        session_key: str,
        session_id: str,
        merged_input: str,
        scene_info: dict[str, Any],
        version: int,
        append_user: bool,
        recovery_depth: int,
        recovery_note: str = "",
    ) -> None:
        try:
            raw_response = await self._generate_reply(
                user_id,
                merged_input,
                scene_info,
                append_user=append_user,
                recovery_note=recovery_note,
            )
        except Exception:
            logger.exception("PolarisAgent LLM 回复生成失败")
            await self._emit_inbox_event(
                event_type="agent.reply_generation_failed",
                session_id=session_id,
                summary="LLM 回复生成失败",
                payload={
                    "agent_id": self.id,
                    "session_key": session_key,
                    "scene_info": scene_info,
                    "merged_input": merged_input,
                    "version": version,
                    "recovery_depth": recovery_depth,
                },
            )
            return

        logger.info(
            "PolarisAgent: LLM 回复生成完成 len=%d preview=%.80s",
            len(raw_response),
            raw_response,
        )

        parsed: dict[str, Any] | None = None
        try:
            parsed = safe_parse_json_object(raw_response)
            if not isinstance(parsed, dict):
                parsed = None
        except (ValueError, json.JSONDecodeError):
            pass

        if parsed is None:
            event_type = (
                "agent.reply_parse_failed"
                if raw_response.strip()
                else "agent.reply_empty"
            )
            summary = (
                "LLM 输出无法解析为结构化动作"
                if raw_response.strip()
                else "LLM 返回空响应"
            )
            logger.warning("PolarisAgent: %s session=%s", summary, session_key)
            await self._emit_inbox_event(
                event_type=event_type,
                session_id=session_id,
                summary=summary,
                payload={
                    "agent_id": self.id,
                    "session_key": session_key,
                    "scene_info": scene_info,
                    "merged_input": merged_input,
                    "raw_response": raw_response,
                    "version": version,
                    "recovery_depth": recovery_depth,
                },
            )
            return

        thought = str(parsed.get("thought", "")).strip()
        actions = parsed.get("actions", [])
        if not isinstance(actions, list):
            actions = []

        logger.info("PolarisAgent: 思考: %.120s", thought)

        if not actions:
            logger.info(
                "PolarisAgent: LLM 决定不执行任何动作 (session=%s)", session_key
            )
            return

        if version > 0 and self._session_versions.get(session_key) != version:
            logger.debug("PolarisAgent: 发送前版本已变更，丢弃回复")
            return

        dispatched_count = 0
        invalid_action_count = 0
        for action in actions:
            if not isinstance(action, dict):
                invalid_action_count += 1
                continue
            command = str(action.get("command") or action.get("cmd") or "").strip()
            params = action.get("params", {})
            if not isinstance(params, dict):
                params = {}
            if not command:
                invalid_action_count += 1
                continue

            if version > 0 and self._session_versions.get(session_key) != version:
                break

            text_content = str(params.get("text", ""))
            if text_content.strip():
                delay = min(1.8, max(0.25, len(text_content) * 0.06))
                await asyncio.sleep(delay)

            if version > 0 and self._session_versions.get(session_key) != version:
                break

            try:
                if self._host is not None:
                    result = await self._host.invoke_command(command, **params)
                    dispatched_count += 1
                    logger.info(
                        "PolarisAgent: 已执行命令 %s params=%s result=%s",
                        command,
                        {k: str(v)[:80] for k, v in params.items()},
                        str(result)[:120],
                    )
                else:
                    logger.warning(
                        "PolarisAgent: host 未注入, 无法执行命令 %s", command
                    )
            except Exception:
                logger.exception("PolarisAgent 执行命令 %s 失败", command)

        if dispatched_count == 0 and actions:
            logger.warning(
                "PolarisAgent: actions 中没有可执行命令 session=%s invalid=%d total=%d",
                session_key,
                invalid_action_count,
                len(actions),
            )

        if dispatched_count > 0:
            await self._append_assistant_message(raw_response)
            logger.info(
                "PolarisAgent: 回复已完成 session=%s user=%s actions=%d",
                session_key,
                user_id,
                dispatched_count,
            )

    async def _generate_reply(
        self,
        user_id: str,
        merged_input: str,
        scene_info: dict[str, Any],
        *,
        append_user: bool = True,
        recovery_note: str = "",
    ) -> str:
        """构建记忆 + 命令 + 场景上下文，调用 LLM 生成结构化回复。"""
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

        memory_context = self._build_memory_context(user_id)
        commands_context = self._build_commands_context()
        scene_context = self._build_scene_context(scene_info, strict=True)

        reply_output_prompt = prompts.REPLY_OUTPUT_STRICT.fill(
            commands=commands_context,
        )

        if messages and messages[-1]["role"] == "user":
            messages[-1]["content"] = scene_context + "\n\n" + messages[-1]["content"]

        system_messages = [
            {"role": "system", "content": memory_context},
            {"role": "system", "content": reply_output_prompt},
        ]
        if recovery_note:
            system_messages.append({"role": "system", "content": recovery_note})

        messages = system_messages + messages

        response = await llm_chat(messages, max_tokens=1024, temperature=0.0)
        return (response or "").strip()

    # ── 对话历史管理 ──────────────────────────────────

    async def _append_user_message(
        self,
        user_id: str,
        input_line: str,
    ) -> list[dict[str, Any]]:
        """将用户消息写入 history.json，返回裁剪后的消息列表（system + 最近 N 条）。"""
        async with self._history_lock:
            history = self._read_history()

            # 兜底合并：上一条同用户消息则拼接
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

            # 裁剪：system + 最近 MESSAGE_WINDOW 条
            recent_start = max(1, len(history) - MESSAGE_WINDOW)
            return history[:1] + history[recent_start:]

    async def _append_assistant_message(self, content: str) -> None:
        """写入 assistant 消息到 history.json。"""
        async with self._history_lock:
            history = self._read_history()
            history.append({"role": "assistant", "content": content})
            self._write_history(history)

    async def _get_recent_history_messages(self) -> list[dict[str, Any]]:
        """读取最近窗口内的历史消息，但不追加新的用户消息。"""
        async with self._history_lock:
            history = self._read_history()
            recent_start = max(1, len(history) - MESSAGE_WINDOW)
            return history[:1] + history[recent_start:]

    def _read_history(self) -> list[dict[str, Any]]:
        """读取 history.json（调用方需持有 _history_lock）。"""
        try:
            if self._history_path.exists():
                content = self._history_path.read_text(encoding="utf-8").strip()
                if content:
                    data = json.loads(content)
                    if isinstance(data, list):
                        return data
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("PolarisAgent 读取 history.json 失败: %s", exc)
        return [{"role": "system", "content": self._soul}]

    def _write_history(self, history: list[dict[str, Any]]) -> None:
        """写入 history.json（调用方需持有 _history_lock）。"""
        self._history_path.parent.mkdir(parents=True, exist_ok=True)
        self._history_path.write_text(
            json.dumps(history, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    async def _emit_inbox_event(
        self,
        event_type: str,
        *,
        session_id: str = "",
        summary: str = "",
        payload: dict[str, Any] | None = None,
    ) -> str:
        """把智能体内部异常转成 inbox 事件，而不是在程序内静默降级。"""
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
        logger.info("PolarisAgent: 已写入 inbox 事件 %s", relative_path)
        return relative_path

    @staticmethod
    def _make_session_key(user_id: str, is_group: bool, group_id: str | None) -> str:
        return f"group:{group_id}:{user_id}" if is_group else f"private:{user_id}"

    @staticmethod
    def _coerce_int(value: Any, default: int = 0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def _build_recovery_note(
        self,
        event_type: str,
        summary: str,
        payload: dict[str, Any],
    ) -> str:
        raw_response = str(payload.get("raw_response", "")).strip()
        lines = [
            "你正在修复自己上一轮的结构化输出失败。",
            f"失败类型: {event_type}",
            f"失败摘要: {summary or '无'}",
            "要求: 忽略口癖、寒暄冲动和人格表演，不要解释失败过程，直接重新给出严格 JSON 动作结果。",
        ]
        if raw_response:
            lines.append(f"上一轮错误输出: {raw_response}")
        return "\n".join(lines)

    # ── 记忆上下文 ─────────────────────────────────────

    def _build_memory_context(self, current_user_id: str) -> str:
        """构建注入 LLM 的长期记忆上下文（前两天日记 + 人际关系印象）。"""
        diaries = self._load_previous_two_diaries()
        impressions = self._load_all_impressions()
        prioritized = self._prioritize_impressions(current_user_id, impressions)

        diary_lines = []
        for item in diaries:
            diary_lines.append(f"## {item['date']}")
            diary_lines.append(item["content"])
        diary_block = "\n".join(diary_lines) if diary_lines else "无"

        if prioritized:
            impression_block = json.dumps(prioritized, ensure_ascii=False, indent=2)
        else:
            impression_block = "{}"

        return prompts.MEMORY_CONTEXT.fill(
            diary_block=diary_block,
            impression_block=impression_block,
        )

    def _build_commands_context(self) -> str:
        if self._host is None:
            return "无可用命令"
        lines: list[str] = []
        for spec in self._host.list_command_specs():
            lines.append(f"### {spec.name}")
            lines.append(f"{spec.description}")
            params = spec.parameters_schema.get("properties", {})
            required = spec.parameters_schema.get("required", [])
            if params:
                lines.append("参数：")
                for pname, pschema in params.items():
                    req_mark = " (必填)" if pname in required else ""
                    ptype = pschema.get("type", "string")
                    pdesc = pschema.get("description", "")
                    lines.append(f"  {pname}: {ptype}{req_mark}  {pdesc}")
            lines.append("")
        return "\n".join(lines) if lines else "无可用命令"

    def _build_scene_context(
        self,
        scene_info: dict[str, Any],
        *,
        strict: bool = False,
    ) -> str:
        is_group = scene_info.get("is_group", False)
        prompt = prompts.REPLY_SCENE_STRICT if strict else prompts.REPLY_SCENE
        return prompt.fill(
            scene_type="群聊" if is_group else "私聊",
            session_id=str(scene_info.get("session_id", "")),
            user_id=str(scene_info.get("user_id", "")),
            group_id=str(scene_info.get("group_id") or "无"),
        )

    def _load_previous_two_diaries(self) -> list[dict[str, str]]:
        diary_dir = Config.DATA_DIR / "app_data" / "im_polaris_diary" / "diaries"
        diaries: list[dict[str, str]] = []
        for days_ago in (1, 2):
            target_date = (datetime.now() - timedelta(days=days_ago)).strftime(
                "%Y-%m-%d"
            )
            json_path = diary_dir / f"{target_date}.json"
            if json_path.exists():
                try:
                    content = json_path.read_text(encoding="utf-8")
                    diaries.append({"date": target_date, "content": content})
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
        direct_related_ids: set[str] = set()

        current_user_impression = impressions.get(user_key) or {}
        for row in current_user_impression.get("relationships", []):
            if isinstance(row, dict):
                target = str(row.get("target_user_id", "")).strip()
                if target:
                    direct_related_ids.add(target)

        for candidate_id, payload in impressions.items():
            for row in payload.get("relationships", []):
                if not isinstance(row, dict):
                    continue
                target = str(row.get("target_user_id", "")).strip()
                if target == user_key:
                    direct_related_ids.add(str(candidate_id))

        ordered_ids: list[str] = []
        if user_key in impressions:
            ordered_ids.append(user_key)
        ordered_ids.extend(
            uid
            for uid in sorted(direct_related_ids)
            if uid in impressions and uid != user_key
        )
        ordered_ids.extend(uid for uid in sorted(impressions) if uid not in ordered_ids)
        return {uid: impressions[uid] for uid in ordered_ids}

    # ── 最近消息滑动窗口 ──────────────────────────────

    @staticmethod
    def _recent_window_seconds() -> float:
        return float(RECENT_MESSAGE_LIMIT) * 60.0

    def _prune_recent_messages(
        self,
        recent: deque[tuple[float, str]],
        now_ts: float | None = None,
    ) -> None:
        current_ts = time.time() if now_ts is None else now_ts
        cutoff = current_ts - self._recent_window_seconds()
        while recent and recent[0][0] < cutoff:
            recent.popleft()

    def _append_recent_message(
        self,
        recent: deque[tuple[float, str]],
        message_line: str,
    ) -> None:
        now_ts = time.time()
        self._prune_recent_messages(recent, now_ts=now_ts)
        recent.append((now_ts, message_line))

    def _get_recent_lines(self, recent: deque[tuple[float, str]]) -> list[str]:
        self._prune_recent_messages(recent)
        return [line for _, line in recent]

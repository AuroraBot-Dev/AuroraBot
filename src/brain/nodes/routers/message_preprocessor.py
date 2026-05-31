"""MessagePreprocessor —— 事件文件读取 → 格式化 → 防抖合并 → 产出 message_queue。

纯机械 Router 节点，零 LLM 调用。守护 inbox 中所有 event_*.json 文件，
将事件统一格式化为自然语言文本，按会话分组并入防抖队列，
防抖结束后产出 ``pipeline/message_queue/*.json`` 供下游 ImpulseGate 消费。
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import TYPE_CHECKING, Any

from src.brain.kernel.base import FileDescriptor, FileUpdate, Router
from src.brain.kernel.state_store import kernel_data_dir, move_to_done, next_record_id
from src.utils.log_utils import get_logger

if TYPE_CHECKING:
    from src.brain.nodes.pipeline_state import SharedPipelineState
    from src.platform.application_host import ApplicationHost

logger = get_logger("MessagePreprocessor")

REPLY_DEBOUNCE_SECONDS = 2.0


class MessagePreprocessor(Router):
    """事件收束 & 消息防抖节点。

    守护 ``inbox/pending/event_*.json``，读取后格式化为自然语言文本，
    按会话分组并入防抖队列。防抖结束后将合并文本产出为
    ``pipeline/message_queue/msg_*.json``。

    系统事件（非 message.received）标记 ``skip_gate: true`` 以跳过门控。
    """

    _default_guards = ["inbox/pending/event_*.json"]  # noqa: RUF012
    _default_produces = ["pipeline/message_queue/*.json"]  # noqa: RUF012

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
                self._enqueue_system_event(data, event_type, input_text)

        return []

    # ═══════════════════════════════════════════════════
    # 事件 → 自然语言文本
    # ═══════════════════════════════════════════════════

    @staticmethod
    def _format_event_as_text(data: dict[str, Any]) -> str:
        event_type = str(data.get("type", ""))
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        summary = str(data.get("summary", "")).strip()
        payload = data.get("payload", {}) if isinstance(data.get("payload"), dict) else {}

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
    # 消息入队
    # ═══════════════════════════════════════════════════

    def _enqueue_message(self, data: dict[str, Any], input_text: str) -> None:
        if self._state is None:
            logger.warning("SharedPipelineState 未注入，无法处理消息")
            return

        payload = data.get("payload", {}) if isinstance(data.get("payload"), dict) else {}
        user_id = str(payload.get("user_id", ""))
        session_id = str(payload.get("session_id", ""))
        is_group = bool(payload.get("is_group", False))
        group_id = str(payload.get("group_id", "")) if is_group else None
        session_key = self._state.make_session_key(user_id, is_group, group_id)

        logger.debug("收到消息 session=%s user=%s text=%s", session_key, user_id, input_text)

        scene_name = "群聊" if is_group else "私聊"
        if is_group:
            self._state.append_recent(self._state.get_group_recent(int(group_id or 0)), input_text)
        else:
            self._state.append_recent(self._state.get_private_recent(user_id), input_text)

        entry = {
            "user_id": user_id,
            "session_key": session_key,
            "session_id": session_id,
            "input_text": input_text,
            "is_group": is_group,
            "group_id": group_id,
            "scene_name": scene_name,
        }
        version = self._state.enqueue_inputs(session_key, [entry])
        asyncio.create_task(  # noqa: RUF006
            self._debounce_and_produce(session_key, version, skip_gate=False)
        )

    # ═══════════════════════════════════════════════════
    # 系统事件入队（跳过门控）
    # ═══════════════════════════════════════════════════

    def _enqueue_system_event(self, data: dict[str, Any], event_type: str, input_text: str) -> None:
        if self._state is None:
            logger.warning("SharedPipelineState 未注入，无法处理系统事件")
            return

        payload = data.get("payload", {}) if isinstance(data.get("payload"), dict) else {}
        session_key = str(payload.get("session_key", f"system:{event_type}"))
        user_id = str(payload.get("user_id", "system"))
        session_id = str(payload.get("session_id", ""))
        is_group = bool(payload.get("is_group", False))
        group_id = str(payload.get("group_id", "")) if is_group else None

        recovery_note = ""
        if event_type.startswith("agent.reply_"):
            recovery_note = "你上一轮的输出不是有效 JSON。现在重新输出，必须只给 JSON 对象。"

        entry = {
            "user_id": user_id,
            "session_key": session_key,
            "session_id": session_id,
            "input_text": input_text,
            "is_group": is_group,
            "group_id": group_id,
            "scene_name": "系统",
            "recovery_note": recovery_note,
        }
        version = self._state.enqueue_inputs(session_key, [entry])
        asyncio.create_task(  # noqa: RUF006
            self._debounce_and_produce(session_key, version, skip_gate=True)
        )

    # ═══════════════════════════════════════════════════
    # 防抖 → 产出 message_queue 文件
    # ═══════════════════════════════════════════════════

    async def _debounce_and_produce(
        self,
        session_key: str,
        version: int,
        *,
        skip_gate: bool = False,
    ) -> None:
        await asyncio.sleep(REPLY_DEBOUNCE_SECONDS)

        if self._state is None:
            return

        if not self._state.is_version_current(session_key, version):
            return

        entries = self._state.pop_pending_inputs(session_key)
        if not entries:
            return

        merged_input = "\n".join(e["input_text"] for e in entries)
        first = entries[0]
        user_id = first["user_id"]
        session_id = first["session_id"]
        is_group = first["is_group"]
        group_id = first["group_id"]
        scene_name = first["scene_name"]
        recovery_note = first.get("recovery_note", "")

        logger.debug("防抖完成 session=%s 合并 %d 条 → message_queue", session_key, len(entries))

        recent = (
            self._state.get_group_recent(int(group_id or 0)) if is_group else self._state.get_private_recent(user_id)
        )
        recent_lines = self._state.get_recent_lines(recent)

        payload: dict[str, Any] = {
            "user_id": user_id,
            "session_key": session_key,
            "session_id": session_id,
            "merged_input": merged_input,
            "is_group": is_group,
            "group_id": group_id,
            "scene_name": scene_name,
            "version": version,
            "skip_gate": skip_gate,
            "recent_lines": recent_lines,
        }
        if recovery_note:
            payload["recovery_note"] = recovery_note

        msg_id = next_record_id("msg")
        relative_path = f"pipeline/message_queue/msg_{msg_id}.json"
        update = FileUpdate(
            descriptor=FileDescriptor(path=relative_path, schema="json"),
            content=payload,
        )

        if self._bus is not None:
            await self._bus.apply_update(update, self.id)
        else:
            logger.warning("事件总线未注入，无法产出 message_queue")

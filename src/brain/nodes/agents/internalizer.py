"""Internalizer —— 内化者：Pool B JSON 事件 → Pool A 第一人称体验叙事。

核心认知 Agent。读取 pipeline/message_queue/*.json 中的结构化事件，
结合当前自我之流（now.md）、自我状态（state.md）和持久记忆（memories/），
通过 LLM 生成第一人称体验叙事，追加到自我之流。

这是 Kernel-gamma 的两个转义者之一（B->A）。不是"翻译器"——是**感知 + 赋予意义**。
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any

from src.brain import prompts
from src.brain.ai.gateway import gateway
from src.brain.kernel.base import Agent, FileDescriptor, FileUpdate
from src.brain.kernel.state_store import kernel_data_dir, move_to_done, next_record_id
from src.brain.nodes.self_stream import SelfStream
from src.utils.log_utils import get_logger

if TYPE_CHECKING:
    from src.platform.application_host import ApplicationHost

logger = get_logger("Internalizer")


class Internalizer(Agent):
    """内化者：结构化事件 → 第一人称体验。

    守护 ``pipeline/message_queue/*.json``。每读到一个事件：
    1. 读取当前自我之流、状态、相关记忆
    2. 调用 LLM，以第一人称感知并赋予意义
    3. 将叙事追加到 self/stream/now.md
    4. 产出 ``pipeline/internalized/*.json`` 触发 Externalizer
    """

    _default_guards = ["pipeline/message_queue/*.json"]  # noqa: RUF012
    _default_produces = ["pipeline/internalized/*.json"]  # noqa: RUF012

    def __init__(
        self,
        node_id: str,
        host: "ApplicationHost | None" = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(node_id, host=host, **kwargs)
        self._stream = SelfStream()

    async def execute(self) -> list[FileUpdate]:
        queue_dir = kernel_data_dir / "pipeline" / "message_queue"
        if not queue_dir.exists():
            return []

        msg_files = sorted(queue_dir.glob("msg_*.json"), key=lambda p: p.name)
        if not msg_files:
            return []

        done_dir = queue_dir / "done"
        done_dir.mkdir(parents=True, exist_ok=True)

        updates: list[FileUpdate] = []

        for msg_file in msg_files:
            try:
                data = json.loads(msg_file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                logger.warning("读取 message_queue 失败 %s: %s", msg_file.name, exc)
                move_to_done(msg_file, done_dir)
                continue
            if not isinstance(data, dict):
                move_to_done(msg_file, done_dir)
                continue

            move_to_done(msg_file, done_dir)

            # 提取事件信息
            envelope = data.get("envelope", {}) if isinstance(data.get("envelope"), dict) else {}
            payload = data.get("payload", {}) if isinstance(data.get("payload"), dict) else {}

            event_text = self._build_event_description(envelope, payload)
            if not event_text:
                continue

            logger.debug(
                "内化事件 session=%s trace=%s",
                envelope.get("session_key", "?"),
                envelope.get("trace_id", "?"),
            )

            try:
                narrative, state_update = await self._internalize(event_text)
            except Exception:
                logger.exception("内化 LLM 调用失败，跳过此事件")
                continue

            if narrative:
                self._stream.append_experience(narrative)
                logger.debug("体验已追加到 now.md (%d chars)", len(narrative))

                if state_update:
                    self._stream.update_state(state_update)
                    logger.debug("状态已更新到 state.md")

                # 产出触发文件，唤醒 Externalizer
                # 携带原始情景上下文，供 Externalizer 填写命令参数时使用
                int_id = next_record_id("int")
                relative_path = f"pipeline/internalized/int_{int_id}.json"
                trigger = FileUpdate(
                    descriptor=FileDescriptor(path=relative_path, schema="json"),
                    content={
                        "envelope": {
                            "id": int_id,
                            "trace_id": envelope.get("trace_id", ""),
                            "source_node": self.id,
                            "timestamp": envelope.get("timestamp", ""),
                        },
                        "payload": {
                            "new_content_length": len(narrative),
                            "session_key": envelope.get("session_key", ""),
                            "event_type": payload.get("event_type", ""),
                            "source": payload.get("source", ""),
                            "merged_input": payload.get("merged_input", ""),
                        },
                    },
                )
                updates.append(trigger)

        return updates

    # ═══════════════════════════════════════════════════
    # 事件描述构建
    # ═══════════════════════════════════════════════════

    @staticmethod
    def _build_event_description(
        envelope: dict[str, Any],
        payload: dict[str, Any],
    ) -> str:
        """从 envelope + payload 构建人类可读的事件描述。"""
        parts: list[str] = []

        merged_input = str(payload.get("merged_input", "")).strip()
        if merged_input:
            parts.append(f"新的事件：\n{merged_input}")
            return "\n".join(parts)

        # fallback：从 envelope 构建
        session_key = str(envelope.get("session_key", ""))
        if session_key:
            parts.append(f"会话：{session_key}")

        timestamp = str(envelope.get("timestamp", ""))
        if timestamp:
            parts.append(f"时间：{timestamp}")

        return "\n".join(parts) if parts else ""

    # ═══════════════════════════════════════════════════
    # 命令列表
    # ═══════════════════════════════════════════════════

    def _build_commands_text(self) -> str:
        """构建可用命令的人类可读列表，注入到内化上下文中。"""
        if self._host is None:
            return "无可用命令"
        lines: list[str] = []
        for spec in self._host.list_command_specs():
            params = spec.parameters_schema.get("properties", {})
            param_entries = [
                f"    {pname}: {pschema.get('type', 'string')} — {pschema.get('description', '')}"
                for pname, pschema in params.items()
            ]
            lines.append(f"- **{spec.name}**: {spec.description}")
            if param_entries:
                lines.extend(param_entries)
        return "\n".join(lines) if lines else "无可用命令"

    # ═══════════════════════════════════════════════════
    # META 解析
    # ═══════════════════════════════════════════════════

    _META_RE = re.compile(r"\[META\]\s*\n(.*?)\[/META\]", re.DOTALL)

    @staticmethod
    def _split_meta(raw: str) -> tuple[str, str | None]:
        """从 LLM 响应中分离叙事文本和 [META] 状态块。

        Returns
        -------
        (narrative, state_update | None)
        """
        match = Internalizer._META_RE.search(raw)
        if not match:
            return raw, None
        narrative = raw[: match.start()].strip()
        state_block = match.group(1).strip()
        # 构建 state.md 格式
        lines = ["# 自我状态", ""]
        for raw_line in state_block.split("\n"):
            stripped = raw_line.strip()
            if stripped and ":" in stripped:
                key, _, value = stripped.partition(":")
                lines.append(f"- {key.strip()}：{value.strip()}")
        lines.append("")
        state_update = "\n".join(lines)
        return narrative, state_update

    # ═══════════════════════════════════════════════════
    # LLM 内化
    # ═══════════════════════════════════════════════════

    async def _internalize(self, event_text: str) -> tuple[str, str | None]:
        """内化事件，返回 (叙事文本, 状态更新文本 | None)。"""
        # 组装上下文
        recent = self._stream.read_recent_chars(3000)
        state = self._stream.read_state()
        memories = self._stream.list_memories()
        commands_text = self._build_commands_text()

        memory_context = ""
        if memories:
            memory_context = f"\n\n## 我已有的记忆\n{', '.join(memories)}"

        user_message = (
            f"## 我当前的状态\n\n{state}\n\n"
            f"## 我最近的意识流\n\n{recent}\n"
            f"{memory_context}\n\n"
            f"## 我可以调用的能力\n\n{commands_text}\n\n"
            f"## 我刚刚感知到的新事件\n\n{event_text}\n\n"
            f"现在，以第一人称把这个新体验写入我的意识流。"
        )

        messages = [
            {"role": "system", "content": prompts.INTERNALIZER.get_content()},
            {"role": "user", "content": user_message},
        ]

        gen = gateway.quality.acompletion(
            messages,
            max_tokens=2048,
            temperature=0.7,
        )
        await gen
        response = gen.plain()
        raw = (response or "").strip()
        return self._split_meta(raw)

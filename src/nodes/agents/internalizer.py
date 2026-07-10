"""Internalizer — 内化者：结构化事件 → 第一人称体验叙事。

核心认知 Agent。读取 pipeline/message_queue/*.json 中的结构化事件，
结合当前自我之流（now.md）、自我状态（state.md）和持久记忆（memories/），
通过 LLM 生成第一人称体验叙事，追加到自我之流。
"""

from __future__ import annotations

import json
import re
from typing import Any

from src import prompts
from src.ai.gateway import gateway
from src.kernel.base import Agent, FileDescriptor, FileUpdate
from src.kernel.state_store import kernel_data_dir, move_to_done, next_record_id
from src.nodes.self_stream import SelfStream
from src.utils.log_utils import get_logger

logger = get_logger("Internalizer")


class Internalizer(Agent):
    """内化者：结构化事件 → 第一人称体验。"""

    _default_guards = ["pipeline/message_queue/*.json"]
    _default_produces = ["pipeline/internalized/*.json"]

    def __init__(self, node_id: str, **kwargs: Any) -> None:
        super().__init__(node_id, **kwargs)
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

    @staticmethod
    def _build_event_description(envelope: dict[str, Any], payload: dict[str, Any]) -> str:
        parts: list[str] = []
        merged_input = str(payload.get("merged_input", "")).strip()
        if merged_input:
            parts.append(f"新的事件：\n{merged_input}")
            return "\n".join(parts)
        session_key = str(envelope.get("session_key", ""))
        if session_key:
            parts.append(f"会话：{session_key}")
        timestamp = str(envelope.get("timestamp", ""))
        if timestamp:
            parts.append(f"时间：{timestamp}")
        return "\n".join(parts) if parts else ""

    _META_RE = re.compile(r"\[META\]\s*\n(.*?)\[/META\]", re.DOTALL)

    @staticmethod
    def _split_meta(raw: str) -> tuple[str, str | None]:
        match = Internalizer._META_RE.search(raw)
        if not match:
            return raw, None
        narrative = raw[: match.start()].strip()
        state_block = match.group(1).strip()
        lines = ["# 自我状态", ""]
        for raw_line in state_block.split("\n"):
            stripped = raw_line.strip()
            if stripped and ":" in stripped:
                key, _, value = stripped.partition(":")
                lines.append(f"- {key.strip()}：{value.strip()}")
        lines.append("")
        state_update = "\n".join(lines)
        return narrative, state_update

    async def _internalize(self, event_text: str) -> tuple[str, str | None]:
        recent = self._stream.read_recent_chars(3000)
        state = self._stream.read_state()
        memories = self._stream.list_memories()

        memory_context = ""
        if memories:
            memory_context = f"\n\n## 我已有的记忆\n{', '.join(memories)}"

        user_message = (
            f"## 我当前的状态\n\n{state}\n\n"
            f"## 我最近的意识流\n\n{recent}\n"
            f"{memory_context}\n\n"
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

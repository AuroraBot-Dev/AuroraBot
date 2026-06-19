"""Externalizer —— 外化者：Pool A 第一人称决定 → Pool B JSON 动作。

核心认知 Agent。读取 pipeline/internalized/*.json 触发信号后，
扫描自我之流（now.md）中最近的思考，识别明确的行动意图
（"我决定..."、"我想..."），转译为结构化 JSON 动作。

这是 Kernel-gamma 的两个转义者之一（A->B）。不是"翻译器"——是**决策 + 行动转义**。
"""

from __future__ import annotations

import json
from typing import Any

from src.brain import prompts
from src.brain.ai.gateway import gateway
from src.brain.kernel.base import Agent, FileDescriptor, FileUpdate
from src.brain.kernel.state_store import kernel_data_dir, move_to_done, next_record_id
from src.brain.nodes.self_stream import SelfStream
from src.utils.log_utils import get_logger

logger = get_logger("Externalizer")


class Externalizer(Agent):
    """外化者：第一人称决定 → JSON 动作。

    由 ``pipeline/internalized/*.json`` 触发。读取自我之流中最近的思考，
    识别明确的行动意图，转译为 JSON 命令。

    如果没有明确的行动意图，不产出任何动作文件。
    """

    _default_guards = ["pipeline/internalized/*.json"]  # noqa: RUF012
    _default_produces = ["pipeline/action_queue/*.json"]  # noqa: RUF012

    def __init__(
        self,
        node_id: str,
        host: object | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(node_id, host=host, **kwargs)
        self._stream = SelfStream()
        self._client_manager: Any = None
        if host is not None:
            from src.platform.mcp_kit.client_manager import MCPClientManager

            if isinstance(host, MCPClientManager):
                self._client_manager = host

    async def execute(self) -> list[FileUpdate]:
        trigger_dir = kernel_data_dir / "pipeline" / "internalized"
        if not trigger_dir.exists():
            return []

        trigger_files = sorted(trigger_dir.glob("int_*.json"), key=lambda p: p.name)
        if not trigger_files:
            return []

        done_dir = trigger_dir / "done"
        done_dir.mkdir(parents=True, exist_ok=True)

        updates: list[FileUpdate] = []

        for trigger_file in trigger_files:
            try:
                data = json.loads(trigger_file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                move_to_done(trigger_file, done_dir)
                continue
            if not isinstance(data, dict):
                move_to_done(trigger_file, done_dir)
                continue

            move_to_done(trigger_file, done_dir)

            envelope = data.get("envelope", {}) if isinstance(data.get("envelope"), dict) else {}
            payload = data.get("payload", {}) if isinstance(data.get("payload"), dict) else {}
            trace_id = str(envelope.get("trace_id", ""))

            # 提取 Internalizer 传递的原始情景
            situation = {
                "session_key": str(payload.get("session_key", "")),
                "event_type": str(payload.get("event_type", "")),
                "source": str(payload.get("source", "")),
                "merged_input": str(payload.get("merged_input", "")),
            }

            logger.debug("外化检查 trace=%s", trace_id)

            try:
                raw = await self._externalize(situation)
            except Exception:
                logger.exception("外化 LLM 调用失败")
                continue

            if not raw or not raw.strip():
                continue

            # 解析 JSON
            parsed = self._parse_actions(raw)
            if parsed is None:
                logger.warning("外化输出无法解析为 JSON: %.200s", raw)
                continue

            actions = parsed.get("actions", [])
            if not isinstance(actions, list) or not actions:
                logger.debug("无待执行动作 trace=%s", trace_id)
                continue

            act_id = next_record_id("act")
            relative_path = f"pipeline/action_queue/act_{act_id}.json"

            payload: dict[str, Any] = {
                "envelope": {
                    "id": act_id,
                    "trace_id": trace_id,
                    "source_node": self.id,
                },
                "payload": {
                    "raw_response": raw,
                    "thought": parsed.get("thought", ""),
                    "actions": actions,
                },
            }

            update = FileUpdate(
                descriptor=FileDescriptor(path=relative_path, schema="json"),
                content=payload,
            )
            updates.append(update)
            logger.info("外化完成 trace=%s actions=%d", trace_id, len(actions))

        return updates

    # ═══════════════════════════════════════════════════
    # LLM 外化
    # ═══════════════════════════════════════════════════

    async def _externalize(self, situation: dict[str, str] | None = None) -> str:
        recent = self._stream.read_recent_chars(4000)
        state = self._stream.read_state()
        commands_text = self._build_commands_text()

        action_prompt = prompts.EXTERNALIZER.fill(commands=commands_text)

        # 构建情景段落
        situation_text = ""
        if situation:
            parts: list[str] = []
            if situation.get("session_key"):
                parts.append(f"会话标识: {situation['session_key']}")
            if situation.get("source"):
                parts.append(f"事件来源: {situation['source']}")
            if situation.get("event_type"):
                parts.append(f"事件类型: {situation['event_type']}")
            if situation.get("merged_input"):
                parts.append(f"原始事件: {situation['merged_input']}")
            if parts:
                situation_text = "## 当前情景（用于填写命令参数）\n\n" + "\n".join(parts) + "\n\n"

        user_message = (
            f"## 我当前的状态\n\n{state}\n\n"
            f"## 我最近的意识流\n\n{recent}\n\n"
            f"{situation_text}"
            f"请识别其中的行动意图并转义为命令。如果没有明确的决定，返回空 actions。"
        )

        messages = [
            {"role": "system", "content": action_prompt},
            {"role": "user", "content": user_message},
        ]

        gen = gateway.quality.acompletion(
            messages,
            max_tokens=2048,
            temperature=0.0,
        )
        await gen
        response = gen.plain()
        return (response or "").strip()

    # ═══════════════════════════════════════════════════
    # 命令列表 & JSON 解析
    # ═══════════════════════════════════════════════════

    def _build_commands_text(self) -> str:
        if self._client_manager is not None:
            return self._client_manager.tools_as_prompt_text()
        return "无可用工具"

    @staticmethod
    def _parse_actions(raw: str) -> dict[str, Any] | None:
        from src.utils.json_utils import parse_llm_json, safe_parse_json_object

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

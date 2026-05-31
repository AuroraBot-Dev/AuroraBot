"""ImpulseGate —— LLM 门控节点。

轻量级 Agent 节点，使用快速模型判断当前消息是否需要完整回复。
读取 ``pipeline/message_queue/*.json``，产出 ``gate_pass/*`` 或 ``gate_skip/*``。
系统事件（skip_gate=true）自动放行，无需 LLM 调用。
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from src.brain import prompts
from src.brain.ai.gateway import gateway
from src.brain.kernel.base import Agent, FileDescriptor, FileUpdate
from src.brain.kernel.state_store import kernel_data_dir, move_to_done, next_record_id
from src.config import Config
from src.utils.log_utils import get_logger

if TYPE_CHECKING:
    from src.brain.nodes.pipeline_state import SharedPipelineState
    from src.platform.application_host import ApplicationHost

logger = get_logger("ImpulseGate")

RECENT_MESSAGE_LIMIT = 6


class ImpulseGate(Agent):
    """脉冲门控节点。

    读取 message_queue 文件，通过轻量 LLM 调用判断是否回复。
    通过 → ``pipeline/gate_pass/msg_*.json``
    跳过 → ``pipeline/gate_skip/msg_*.json``

    系统事件（skip_gate=true）或 private:localhost 会话自动放行。
    """

    _default_guards = ["pipeline/message_queue/*.json"]  # noqa: RUF012
    _default_produces = [  # noqa: RUF012
        "pipeline/gate_pass/*.json",
        "pipeline/gate_skip/*.json",
    ]

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

            session_id = str(data.get("session_id", ""))
            skip_gate = bool(data.get("skip_gate", False))

            passed: bool
            if skip_gate or session_id == "private:localhost":
                passed = True
                logger.debug("跳过门控 session=%s skip_gate=%s", data.get("session_key"), skip_gate)
            else:
                try:
                    passed = await self._check_gate(data)
                except Exception:
                    logger.exception("门控异常，默认不回复")
                    passed = False

            gate_id = next_record_id("gate")
            subdir = "gate_pass" if passed else "gate_skip"
            relative_path = f"pipeline/{subdir}/gate_{gate_id}.json"

            update = FileUpdate(
                descriptor=FileDescriptor(path=relative_path, schema="json"),
                content=data,
            )
            updates.append(update)

            logger.debug(
                "门控结果=%s session=%s → %s",
                "PASS" if passed else "SKIP",
                data.get("session_key"),
                relative_path,
            )

        return updates

    async def _check_gate(self, data: dict[str, Any]) -> bool:
        scene_name = str(data.get("scene_name", ""))
        recent_lines = data.get("recent_lines", [])
        if not isinstance(recent_lines, list):
            recent_lines = []
        merged_input = str(data.get("merged_input", ""))

        recent_text = "\n".join(recent_lines) if recent_lines else "(暂无历史)"
        soul = self._state.soul if self._state else ""

        messages = [
            {"role": "system", "content": prompts.GATE.get_content()},
            {
                "role": "user",
                "content": prompts.GATE_USER.fill(
                    soul=soul,
                    scene_name=scene_name,
                    recent_limit=str(RECENT_MESSAGE_LIMIT),
                    recent_text=recent_text,
                    merged_input=merged_input,
                ),
            },
        ]
        try:
            gen = gateway.fast.acompletion(
                messages,
                max_tokens=512,
                temperature=0.0,
                timeout=Config.LLM_GATE_TIMEOUT,
            )
            await gen
            response = gen.plain()
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
        return "是" in content

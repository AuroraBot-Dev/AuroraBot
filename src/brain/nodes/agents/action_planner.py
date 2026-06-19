"""ActionPlanner —— LLM 动作规划节点。

核心 Agent 节点，使用质量模型根据对话上下文生成 JSON 动作列表。
读取 ``pipeline/gate_pass/*.json``，组装对话历史 + 记忆上下文 + 命令列表，
调用 LLM 生成动作，产出 ``pipeline/action_queue/*.json``。
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from src.brain import prompts
from src.brain.ai.gateway import GatewayError, gateway
from src.brain.kernel.base import Agent, FileDescriptor, FileUpdate
from src.brain.kernel.state_store import kernel_data_dir, move_to_done, next_record_id
from src.config import Config
from src.utils.log_utils import get_logger

logger = get_logger("ActionPlanner")

ACTION_WINDOW = 50
MESSAGE_WINDOW = 300


class ActionPlanner(Agent):
    """动作规划节点。

    读取 gate_pass 文件，组装完整上下文后调用质量 LLM 生成 JSON 动作列表。
    产出 ``pipeline/action_queue/act_*.json`` 供 CommandDispatcher 消费。

    LLM 调用失败时写入 inbox 事件自恢复。
    """

    _default_guards = ["pipeline/gate_pass/*.json"]  # noqa: RUF012
    _default_produces = ["pipeline/action_queue/*.json"]  # noqa: RUF012

    def __init__(
        self,
        node_id: str,
        host: "object | None" = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(node_id, host=host, **kwargs)
        self._state: Any = None  # Kernel-beta 遗留，gamma 中已移除 SharedPipelineState

    async def execute(self) -> list[FileUpdate]:
        gate_dir = kernel_data_dir / "pipeline" / "gate_pass"
        if not gate_dir.exists():
            return []

        gate_files = sorted(gate_dir.glob("gate_*.json"), key=lambda p: p.name)
        if not gate_files:
            return []

        done_dir = gate_dir / "done"
        done_dir.mkdir(parents=True, exist_ok=True)

        updates: list[FileUpdate] = []

        for gate_file in gate_files:
            try:
                data = json.loads(gate_file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                logger.warning("读取 gate_pass 失败 %s: %s", gate_file.name, exc)
                move_to_done(gate_file, done_dir)
                continue
            if not isinstance(data, dict):
                move_to_done(gate_file, done_dir)
                continue

            move_to_done(gate_file, done_dir)

            user_id = str(data.get("user_id", ""))
            session_key = str(data.get("session_key", ""))
            session_id = str(data.get("session_id", ""))
            merged_input = str(data.get("merged_input", ""))
            is_group = bool(data.get("is_group", False))
            group_id = str(data.get("group_id", "")) if data.get("group_id") else None
            version = int(data.get("version", 0))
            recovery_note = str(data.get("recovery_note", ""))

            try:
                raw = await self._generate_actions(
                    user_id=user_id,
                    merged_input=merged_input,
                    session_id=session_id,
                    is_group=is_group,
                    group_id=group_id,
                    recovery_note=recovery_note,
                )
            except GatewayError as exc:
                logger.exception("LLM 动作生成失败")
                await self._emit_inbox_event(
                    "agent.reply_generation_failed",
                    session_key=session_key,
                    merged_input=merged_input,
                    is_group=is_group,
                    group_id=group_id,
                    version=version,
                    reason=str(exc),
                )
                continue
            except Exception:
                logger.exception("LLM 动作生成失败")
                await self._emit_inbox_event(
                    "agent.reply_generation_failed",
                    session_key=session_key,
                    merged_input=merged_input,
                    is_group=is_group,
                    group_id=group_id,
                    version=version,
                )
                continue

            logger.debug("动作生成完成 len=%d preview=%s", len(raw), raw[:200] if raw else "")

            act_id = next_record_id("act")
            relative_path = f"pipeline/action_queue/act_{act_id}.json"

            payload: dict[str, Any] = {
                "user_id": user_id,
                "session_key": session_key,
                "session_id": session_id,
                "merged_input": merged_input,
                "is_group": is_group,
                "group_id": group_id,
                "version": version,
                "recovery_note": recovery_note,
                "raw_response": raw,
            }

            update = FileUpdate(
                descriptor=FileDescriptor(path=relative_path, schema="json"),
                content=payload,
            )
            updates.append(update)

        return updates

    # ═══════════════════════════════════════════════════
    # LLM 动作生成
    # ═══════════════════════════════════════════════════

    async def _generate_actions(  # noqa: PLR0913
        self,
        *,
        user_id: str,
        merged_input: str,
        session_id: str,
        is_group: bool,
        group_id: str | None,
        recovery_note: str = "",
    ) -> str:
        t0 = time.time()

        logger.debug("[动作规划] step=历史加载 user=%s", user_id)
        if self._state is not None:
            messages = await self._state.append_user_message(user_id, merged_input)
        else:
            messages = [{"role": "user", "content": merged_input}]
        logger.debug("[动作规划] step=历史加载 耗时=%.2fs len=%d", time.time() - t0, len(messages))

        # 移除 system 消息（LLM 调用时单独注入）
        if messages and messages[0].get("role") == "system":
            messages = messages[1:]

        # 裁剪到最近 ACTION_WINDOW 条
        recent_start = max(0, len(messages) - ACTION_WINDOW)
        messages = messages[recent_start:]

        t1 = time.time()
        scene_text = self._build_scene_text(session_id, is_group, group_id)
        commands_text = self._build_commands_text()
        memory_text = self._build_memory_text(user_id)
        logger.debug("[动作规划] step=上下文构建 耗时=%.2fs", time.time() - t1)

        t2 = time.time()
        advanced_memory_text = await self._fetch_advanced_memory(user_id, merged_input)
        logger.debug("[动作规划] step=高级记忆 耗时=%.2fs", time.time() - t2)

        combined_memory_text = f"{memory_text}\n\n{advanced_memory_text}" if advanced_memory_text else memory_text

        action_prompt = prompts.ACTION.fill(
            scene=scene_text,
            commands=commands_text,
        )

        final_instruction = f"{action_prompt}\n\n（只输出 JSON。第一个字符 {{，最后一个 }}。不要任何其他文字。）"
        if recovery_note:
            final_instruction = f"{recovery_note}\n\n{final_instruction}"

        messages.append({"role": "user", "content": final_instruction})

        t3 = time.time()
        logger.debug(
            "[动作规划] step=LLM调用 model=%s msg_count=%d max_tokens=2048",
            Config.LLM_GATEWAY_QUALITY_MODEL,
            len(messages),
        )
        gen = gateway.quality.acompletion(
            [{"role": "system", "content": combined_memory_text}, *messages],
            max_tokens=2048,
            temperature=0.0,
        )
        await gen
        response = gen.plain()
        logger.debug(
            "[动作规划] step=LLM调用 耗时=%.2fs len=%d",
            time.time() - t3,
            len(response) if response else 0,
        )
        logger.debug("[动作规划] 总耗时=%.2fs", time.time() - t0)
        return (response or "").strip()

    # ═══════════════════════════════════════════════════
    # 场景 & 命令 & 记忆 上下文构建
    # ═══════════════════════════════════════════════════

    @staticmethod
    def _build_scene_text(
        session_id: str,
        is_group: bool,  # noqa: FBT001
        group_id: str | None,
    ) -> str:
        stype = "群聊" if is_group else "私聊"
        gid = group_id or "无"
        return f"会话类型: {stype}\n会话 ID: {session_id}\n群号: {gid}"

    def _build_commands_text(self) -> str:
        if self._host is None:
            return "无可用命令"
        lines: list[str] = []
        for spec in self._host.list_command_specs():  # type: ignore[attr-defined]
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
        if self._state is None:
            diaries: list[dict[str, str]] = []
            impressions: dict[str, Any] = {}
        else:
            diaries = self._state.load_previous_two_diaries()
            impressions = self._state.load_all_impressions()

        if self._state is not None:
            prioritized = self._state.prioritize_impressions(current_user_id, impressions)
        else:
            prioritized = impressions

        diary_lines = [f"## {d['date']}\n{d['content']}" for d in diaries]
        diary_block = "\n".join(diary_lines) if diary_lines else "无"

        impression_block = json.dumps(prioritized, ensure_ascii=False, indent=2) if prioritized else "{}"
        return prompts.MEMORY.fill(
            diary_block=diary_block,
            impression_block=impression_block,
        )

    async def _fetch_advanced_memory(self, user_id: str, current_query: str) -> str:
        if self._memory is None:
            return ""
        loop = asyncio.get_running_loop()
        try:
            ctx = await loop.run_in_executor(None, self._memory.retrieve_context, current_query, user_id)
            return ctx.to_prompt_text()
        except Exception:
            logger.exception("获取高级统一记忆失败")
            return ""

    # ═══════════════════════════════════════════════════
    # 错误恢复：写入 inbox 事件
    # ═══════════════════════════════════════════════════

    async def _emit_inbox_event(  # noqa: PLR0913
        self,
        event_type: str,
        *,
        session_key: str,
        merged_input: str,
        is_group: bool,
        group_id: str | None,
        version: int,
        reason: str = "",
    ) -> None:
        safe_type = str(event_type).replace(".", "_").replace("/", "_")
        event_id = next_record_id("evt")
        relative_path = f"inbox/pending/event_{safe_type}_{event_id}.json"

        payload: dict[str, Any] = {
            "session_key": session_key,
            "merged_input": merged_input,
            "is_group": is_group,
            "group_id": group_id,
            "version": version,
        }
        if reason:
            payload["reason"] = reason

        # 从 gate_pass 携带的原始数据中提取 user/session 信息
        event = {
            "source": self.id,
            "type": event_type,
            "session_id": "",
            "summary": "LLM 动作生成失败",
            "payload": payload,
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

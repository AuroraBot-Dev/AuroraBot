"""把稳定身份、压缩记忆和当前事件装配成最小模型上下文。"""

from __future__ import annotations

import json
from enum import StrEnum
from typing import TYPE_CHECKING

from src.prompt.models import PromptCatalog, PromptDocument, PromptSection

if TYPE_CHECKING:
    from src.contracts.agent import AgentContext
    from src.contracts.model import ModelMessage


class _Msg(StrEnum):
    """本文件内所有用户或模型可见的硬编码文本。"""

    ADMITTED_EVENTS = "处理这批刚刚接纳的会话事件：\n{content}"
    CHILD_RESULT = "子代理返回：\n{content}"
    CURRENT_MESSAGE = "处理当前消息：\n{content}"
    EXTERNAL_DATA = '<external-data encoding="json">\n{encoded}\n</external-data>'
    LOCAL_WORK = "当前局部工作：\n{content}"
    MISSING_AGENT_PROMPT = "missing prompt for Agent profile {profile_id}"
    MEMORY_WINDOW = "[ 最近对话 ]\n{content}"
    REMOTE_SUMMARIES = "[ 其他会话摘要 ]\n{content}"
    REMOTE_WINDOW = "[ 其他会话最近动态 ]\n{content}"
    RELEVANT_FACTS = "[ 相关长期事实 ]\n{content}"
    SESSION_MEMORY = "[ 会话摘要 ]\n{content}"
    TOOL_RESULT = "工具返回 {status}：\n{content}"


class MissingAgentPromptError(ValueError):
    def __init__(self, profile_id: str) -> None:
        super().__init__(_Msg.MISSING_AGENT_PROMPT.format(profile_id=profile_id))


class PromptComposer:
    """稳定 System + 可选 Memory System + 当前 User 事实。"""

    def __init__(self, catalog: PromptCatalog) -> None:
        self._catalog = catalog

    def request_document(self, context: AgentContext) -> PromptDocument:
        try:
            agent_prompt = self._catalog.agents[context.profile.id]
        except KeyError as error:
            raise MissingAgentPromptError(context.profile.id) from error
        system: list[PromptSection] = []
        if self._catalog.soul.strip():
            system.append(PromptSection("soul", self._catalog.soul))
        system.extend((PromptSection("world", self._catalog.world), PromptSection("agent_profile", agent_prompt)))
        memory: list[PromptSection] = []
        if context.memory.summary.strip():
            memory.append(
                PromptSection(
                    "session_memory",
                    _Msg.SESSION_MEMORY.format(content=external_data(context.memory.summary)),
                )
            )
        if context.memory.window:
            memory.append(
                PromptSection(
                    "memory_window",
                    _Msg.MEMORY_WINDOW.format(
                        content=external_data([f"{item.role}: {item.content}" for item in context.memory.window])
                    ),
                )
            )
        if context.memory.remote_summaries:
            memory.append(
                PromptSection(
                    "remote_summaries",
                    _Msg.REMOTE_SUMMARIES.format(
                        content=external_data(
                            [{"scope": item.scope, "summary": item.summary} for item in context.memory.remote_summaries]
                        )
                    ),
                )
            )
        if context.memory.remote_window:
            memory.append(
                PromptSection(
                    "remote_window",
                    _Msg.REMOTE_WINDOW.format(
                        content=external_data(
                            [
                                {"scope": item.scope, "role": item.role, "content": item.content}
                                for item in context.memory.remote_window
                            ]
                        )
                    ),
                )
            )
        if context.memory.relevant_facts:
            memory.append(
                PromptSection(
                    "relevant_facts",
                    _Msg.RELEVANT_FACTS.format(content=external_data(context.memory.relevant_facts)),
                )
            )
        user = [PromptSection("message", _message_text(context))]
        work = _local_work(context)
        if work:
            user.append(PromptSection("local_work", work))
        return PromptDocument(tuple(system), tuple(user), tuple(memory))

    def request_messages(self, context: AgentContext) -> tuple[ModelMessage, ...]:
        return self.request_document(context).messages()


def _message_text(context: AgentContext) -> str:
    payload = context.message.payload
    if context.message.type == "task.started" and isinstance(payload.get("batch"), dict):
        # 入口 triage Task 的批次投影；TriageAgent 自构请求，此分支供通用渲染兜底
        admitted = {"events": payload["batch"].get("events", [])}
        return _Msg.ADMITTED_EVENTS.format(content=external_data(admitted))
    if context.message.type == "agent.assigned" and isinstance(payload.get("context_events"), list):
        # 入口 agent 委派时把有界批次投影交给本体意识
        assigned = {"instruction": context.agent.assignment, "events": payload["context_events"]}
        return _Msg.ADMITTED_EVENTS.format(content=external_data(assigned))
    if context.message.type.startswith("tool."):
        status = context.message.type.removeprefix("tool.")
        request = payload.get("request")
        request_fact = {}
        if isinstance(request, dict):
            request_fact = {
                key: request[key] for key in ("capability", "parameters", "complete_task") if key in request
            }
        outcome_key = "result" if status == "succeeded" else "error"
        return _Msg.TOOL_RESULT.format(
            status=status,
            content=external_data({"request": request_fact, outcome_key: payload.get(outcome_key)}),
        )
    if context.message.type.startswith("child."):
        return _Msg.CHILD_RESULT.format(content=external_data(payload))
    value = context.task.root_summary if context.message.type == "task.started" else context.agent.assignment
    return _Msg.CURRENT_MESSAGE.format(content=external_data(value))


def external_data(value: object) -> str:
    """把外部数据编码为紧凑 JSON 并装入 external-data 模板（prompt 与 triage 共用）。

    编码后转义 HTML 特殊字符，防止模型上下文注入。
    """
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    encoded = encoded.replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")
    return _Msg.EXTERNAL_DATA.format(encoded=encoded)


def _local_work(context: AgentContext) -> str:
    children = [
        {
            "agent_id": child.agent_id,
            "assignment": child.assignment,
            "status": child.status,
            "last_summary": child.last_summary,
        }
        for child in context.children
        if not child.terminal
    ]
    if context.agent.parent_agent_id is None and not children:
        return ""
    return _Msg.LOCAL_WORK.format(
        content=external_data({"assignment": context.agent.assignment, "active_children": children})
    )

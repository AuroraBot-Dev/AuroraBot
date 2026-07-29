"""把稳定身份、压缩记忆和当前事件装配成最小模型上下文。"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from src.prompt.models import PromptCatalog, PromptDocument, PromptSection

if TYPE_CHECKING:
    from src.contracts.agent import AgentContext
    from src.contracts.model import ModelMessage


class MissingAgentPromptError(ValueError):
    def __init__(self, profile_id: str) -> None:
        super().__init__(f"missing prompt for Agent profile {profile_id}")


class PromptComposer:
    """稳定 System + 可选 Memory System + 当前 User 事实。"""

    def __init__(self, catalog: PromptCatalog) -> None:
        self._catalog = catalog

    @property
    def catalog(self) -> PromptCatalog:
        return self._catalog

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
        if context.memory.session_summary.strip():
            memory.append(PromptSection("session_memory", f"[ 会话摘要 ]\n{_external(context.memory.session_summary)}"))
        if context.memory.relevant_facts:
            memory.append(
                PromptSection("relevant_facts", f"[ 相关长期事实 ]\n{_external(context.memory.relevant_facts)}")
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
    events = payload.get("events")
    if context.message.type == "task.started" and isinstance(events, list):
        admitted = {"triage": payload.get("triage"), "events": events}
        return f"处理这批刚刚接纳的会话事件：\n{_external(admitted)}"
    if context.message.type.startswith("tool."):
        status = context.message.type.removeprefix("tool.")
        request = payload.get("request")
        request_fact = {}
        if isinstance(request, dict):
            request_fact = {
                key: request[key] for key in ("capability", "parameters", "complete_task") if key in request
            }
        outcome_key = "result" if status == "succeeded" else "error"
        return f"工具返回 {status}：\n{_external({'request': request_fact, outcome_key: payload.get(outcome_key)})}"
    if context.message.type.startswith("child."):
        return f"子代理返回：\n{_external(payload)}"
    value = context.task.root_summary if context.message.type == "task.started" else context.agent.assignment
    return f"处理当前消息：\n{_external(value)}"


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
    return f"当前局部工作：\n{_external({'assignment': context.agent.assignment, 'active_children': children})}"


def _external(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    encoded = encoded.replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")
    return f'<external-data encoding="json">\n{encoded}\n</external-data>'

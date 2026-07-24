"""从目录文本和事实性 Agent 上下文中装配分层模型提示词。"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from src.prompt.models import PromptCatalog, PromptDocument, PromptSection
from src.prompt.text import CHANNEL_LABELS

if TYPE_CHECKING:
    from src.contracts.agent import AgentContext, CapabilityDescriptor
    from src.contracts.model import ModelMessage


class MissingAgentPromptError(ValueError):
    """指定的 Agent 档案在提示词目录中缺少对应提示词模板时抛出。"""

    def __init__(self, profile_id: str) -> None:
        super().__init__(f"missing prompt for Agent profile {profile_id}")


class PromptComposer:
    """提示词装配的唯一边界——将目录文本和 Agent 上下文组合为模型输入。"""

    def __init__(self, catalog: PromptCatalog) -> None:
        self._catalog = catalog

    @property
    def catalog(self) -> PromptCatalog:
        """返回当前绑定的提示词目录。"""
        return self._catalog

    def request_document(self, context: AgentContext) -> PromptDocument:
        """从 Agent 上下文构建一份完整的提示词文档（system + user sections）。"""
        try:
            agent_prompt = self._catalog.agents[context.profile.id]
        except KeyError as error:
            raise MissingAgentPromptError(context.profile.id) from error
        system: list[PromptSection] = []
        if self._catalog.soul.strip():
            system.append(PromptSection("soul", self._catalog.soul))
        system.extend(
            (
                PromptSection("world", self._catalog.world),
                PromptSection("agent_profile", agent_prompt),
            )
        )
        user: list[PromptSection] = []
        source = _source_note(context)
        if source:
            user.append(PromptSection("source", source))
        user.append(PromptSection("message", _message_text(context)))
        current_work = _current_work(context)
        if current_work:
            user.append(PromptSection("current_work", current_work))
        situations = _situations(context)
        if situations:
            user.append(PromptSection("situations", situations))
        conversation = _recall_conversation(context)
        if conversation:
            user.append(PromptSection("recent_conversation", conversation))
        recalled = _recall_semantic_facts(context)
        if recalled:
            user.append(PromptSection("related_memories", recalled))
        tools = _tool_hints(context.capabilities)
        if tools:
            user.append(PromptSection("available_tools", tools))
        return PromptDocument(tuple(system), tuple(user))

    def request_messages(self, context: AgentContext) -> tuple[ModelMessage, ModelMessage]:
        """直接返回可投喂给模型的 System+User 消息对。"""
        return self.request_document(context).messages()


def _message_text(context: AgentContext) -> str:
    """根据消息类型渲染对应的用户提示文本。"""
    amp = _amp(context)
    if amp is not None:
        payload = amp.get("payload")
        if isinstance(payload, dict):
            return f"收到的完整内容：\n{_external(payload)}"
    if context.message.type.startswith("tool."):
        status = context.message.type.removeprefix("tool.")
        request = context.message.payload.get("request")
        request_fact = {}
        if isinstance(request, dict):
            request_fact = {
                key: request[key] for key in ("capability", "parameters", "complete_task") if key in request
            }
        outcome_key = "result" if status == "succeeded" else "error"
        outcome = {"request": request_fact, outcome_key: context.message.payload.get(outcome_key)}
        return f"刚才的工具返回了 {status}：\n{_external(outcome)}"
    if context.message.type.startswith("child."):
        return f"子代理返回了结果：\n{_external(context.message.payload)}"
    value = context.task.root_summary if context.message.type == "task.started" else context.agent.assignment
    return f"收到消息：\n{_external(value)}"


def _source_note(context: AgentContext) -> str:
    """从 AMP 信封解析来源渠道信息，生成来源标注。"""
    amp = _amp(context)
    if amp is None:
        return ""
    payload = amp.get("payload")
    data = payload.get("data") if isinstance(payload, dict) else None
    channel = data.get("channel") if isinstance(data, dict) else None
    label = CHANNEL_LABELS.get(channel) if isinstance(channel, str) else None
    header = amp.get("header")
    facts: dict[str, object] = {"header": header}
    if isinstance(channel, str):
        facts["channel"] = channel
    username = data.get("sender_username") if isinstance(data, dict) else None
    if isinstance(username, str):
        facts["sender_username"] = username
    introduction = f"[ {label} ]" if label is not None else "[ 未知来源 ]"
    return f"{introduction}\n{_external(facts)}"


def _current_work(context: AgentContext) -> str:
    """生成当前工作状态快照：自身任务、活跃子 Agent、全局活动概览。"""
    active_children = [child for child in context.children if not child.terminal]
    facts = {
        "current": {
            "task_id": context.task.task_id,
            "agent_id": context.agent.agent_id,
            "assignment": context.agent.assignment,
        },
        "active_children": [
            {
                "agent_id": child.agent_id,
                "assignment": child.assignment,
                "status": child.status,
                "last_summary": child.last_summary,
            }
            for child in active_children
        ],
        "global_activity": {
            "active_tasks": context.brain.active_tasks,
            "active_agents": context.brain.active_agents,
            "generated_at": context.brain.generated_at,
        },
    }
    return f"这是我此刻接住的工作，以及同一片活动空间里的进展：\n{_external(facts)}"


def _situations(context: AgentContext) -> str:
    """渲染环境态势列表，让 Agent 按 situation_id 认领工作。"""
    if not context.brain.ambient_situations:
        return ""
    introduction = "我有这些事要做；认领时要使用其中的 situation_id："
    return f"{introduction}\n{_external(context.brain.ambient_situations)}"


def _tool_hints(capabilities: tuple[CapabilityDescriptor, ...]) -> str:
    """生成当前可用的工具能力清单提示。"""
    if not capabilities:
        return ""
    facts = tuple({"id": item.id, "description": item.description} for item in capabilities)
    return f"这些能力此刻可以使用：\n{_external(facts)}"


def _amp(context: AgentContext) -> dict[str, Any] | None:
    """从消息 payload 中提取 AMP 信封（若存在）。"""
    value = context.message.payload.get("amp")
    return value if isinstance(value, dict) else None


def _external(value: object) -> str:
    """将任意值序列化为安全的 `<external-data>` XML 块，防止注入。"""
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    encoded = encoded.replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")
    return f'<external-data encoding="json">\n{encoded}\n</external-data>'


def _recall_semantic_facts(context: AgentContext) -> str:
    """渲染 engine 已召回的语义记忆。"""
    facts = context.memory.related_memories
    if not facts:
        return ""
    return f"[ 相关记忆 ]\n{_external(facts)}"


def _recall_conversation(context: AgentContext) -> str:
    """渲染 engine 已召回的最近对话。"""
    turns = context.memory.recent_conversation
    if not turns:
        return ""
    lines: list[str] = []
    for turn in turns:
        if turn.user.strip():
            lines.append(f"用户：{turn.user}")
        if turn.assistant is not None and turn.assistant.strip():
            lines.append(f"Aurora：{turn.assistant}")
    if not lines:
        return ""
    return "[ 最近对话 ]\n" + "\n".join(lines)

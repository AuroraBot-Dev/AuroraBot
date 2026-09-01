"""把一个 AgentNode 组装为四角色 chat-completion 上下文。"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from src.contracts import AgentTree, ChatMessage, MemorySnapshot

if TYPE_CHECKING:
    from src.prompt.models import PromptCatalog

_TRUNCATION_TAG = "TODO：上下文超过长度上限，较早消息已截断"


class PromptAssembler:
    """无 I/O、无记忆旁路的确定性提示词组装器。"""

    def __init__(self, catalog: PromptCatalog, *, max_characters: int = 32_000) -> None:
        if max_characters <= 0:
            raise ValueError("max_characters must be positive")
        self._catalog = catalog
        self._max_characters = max_characters

    @property
    def catalog(self) -> PromptCatalog:
        """暴露当前提示词目录给组合与监测；组装逻辑不依赖此属性。"""
        return self._catalog

    def assemble(
        self,
        tree: AgentTree,
        node_id: str,
        *,
        memory: MemorySnapshot | None = None,
    ) -> tuple[ChatMessage, ...]:
        node = tree.node(node_id)
        try:
            agent_prompt = self._catalog.agent_prompts[node.prompt_id]
        except KeyError as error:
            raise ValueError(f"missing Agent prompt：{node.prompt_id}") from error
        fragments = [*self._catalog.system]
        if memory is not None:
            fragments.append(self._render_memory(memory))
        system = ChatMessage.system("\n\n".join((*fragments, agent_prompt)))
        messages = (system, *node.messages)
        if _total_size(messages) <= self._max_characters:
            return messages
        if len(system.content) + len(_TRUNCATION_TAG) > self._max_characters:
            return (ChatMessage.system(_bounded(system.content, _TRUNCATION_TAG, self._max_characters)),)
        kept = list(node.messages)
        budget = self._max_characters - len(system.content) - len(_TRUNCATION_TAG)
        while kept and _total_size(kept) > budget:
            kept.pop(0)
        while kept and kept[0].role == "tool":
            kept.pop(0)
        return (system, ChatMessage.message(_TRUNCATION_TAG), *kept)

    @staticmethod
    def _render_memory(memory: MemorySnapshot) -> str:
        lines = ["## 最近时间窗口内的世界活动", f"窗口起点：{memory.window_start.isoformat()}"]
        for scope in memory.scopes:
            lines.append(f"### scope：{scope.scope}（head={scope.head}）")
            for commit in scope.commits:
                lines.append(f"- {commit.occurred_at.isoformat()} [{commit.kind}] {commit.summary}")
                if commit.data:
                    lines.append(f"  数据：{json.dumps(dict(commit.data), ensure_ascii=False, separators=(',', ':'))}")
        return "\n".join(lines)


def _message_size(message: ChatMessage) -> int:
    return len(message.content) + sum(
        len(call.call_id) + len(call.name) + len(json.dumps(dict(call.arguments))) for call in message.tool_calls
    )


def _total_size(messages: tuple[ChatMessage, ...] | list[ChatMessage]) -> int:
    return sum(_message_size(message) for message in messages)


def _bounded(content: str, tag: str, limit: int) -> str:
    if len(tag) >= limit:
        return tag[:limit]
    return f"{content[: limit - len(tag)]}{tag}"

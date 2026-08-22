"""把一个 AgentNode 组装为四角色 chat-completion 上下文。"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from src.contracts import AgentTree, ChatMessage, MemorySnapshot

if TYPE_CHECKING:
    from src.prompt.models import PromptCatalog


class PromptAssembler:
    """无 I/O、无记忆旁路的确定性提示词组装器。"""

    def __init__(self, catalog: PromptCatalog, *, max_characters: int = 32_000) -> None:
        if max_characters <= 0:
            raise ValueError("max_characters must be positive")
        self._catalog = catalog
        self._max_characters = max_characters

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
        size = sum(
            len(message.content)
            + sum(
                len(call.call_id) + len(call.name) + len(json.dumps(dict(call.arguments)))
                for call in message.tool_calls
            )
            for message in messages
        )
        if size > self._max_characters:
            raise ValueError(f"prompt exceeds character limit: {size} > {self._max_characters}")
        return messages

    @staticmethod
    def _render_memory(memory: MemorySnapshot) -> str:
        lines = ["## 最近一小时的世界活动", f"窗口起点：{memory.window_start.isoformat()}"]
        for scope in memory.scopes:
            lines.append(f"### scope：{scope.scope}（head={scope.head}）")
            for commit in scope.commits:
                lines.append(f"- {commit.occurred_at.isoformat()} [{commit.kind}] {commit.summary}")
                if commit.data:
                    lines.append(f"  数据：{json.dumps(dict(commit.data), ensure_ascii=False, separators=(',', ':'))}")
        return "\n".join(lines)

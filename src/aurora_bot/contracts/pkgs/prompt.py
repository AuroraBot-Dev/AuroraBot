"""``prompt`` 暴露的全局端口：提示词目录与组装契约。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Mapping

    from aurora_bot.contracts.model import ChatMessage
    from aurora_bot.contracts.prompt import PromptAssembly, PromptFragment
    from aurora_bot.contracts.resource import ResourceRef
    from aurora_bot.contracts.tool import ToolDefinition
    from aurora_bot.contracts.world import MemorySnapshot


class PromptCatalog(Protocol):
    """四角色提示词目录。"""

    @property
    def fragments(self) -> tuple[PromptFragment, ...]: ...

    @property
    def system(self) -> tuple[str, ...]: ...

    @property
    def agent_prompts(self) -> Mapping[str, str]: ...

    def get(self, ref: ResourceRef) -> PromptFragment: ...

    def for_agent(self, prompt_id: str) -> tuple[PromptFragment, ...]: ...


class PromptAssembler(Protocol):
    """把节点组装为模型上下文的确定性组装器。"""

    @property
    def catalog(self) -> PromptCatalog: ...

    def assemble(
        self,
        prompt_id: str,
        messages: tuple[ChatMessage, ...],
        *,
        memory: MemorySnapshot | None = None,
        tools: tuple[ToolDefinition, ...] = (),
    ) -> PromptAssembly: ...

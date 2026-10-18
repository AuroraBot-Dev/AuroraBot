"""``prompt`` 暴露的全局端口：提示词目录与组装契约。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Mapping

    from src.contracts.agent import AgentTree
    from src.contracts.prompt import PromptAssembly
    from src.contracts.world import MemorySnapshot


class PromptCatalog(Protocol):
    """四角色提示词目录。"""

    @property
    def system(self) -> tuple[str, ...]: ...

    @property
    def agent_prompts(self) -> Mapping[str, str]: ...


class PromptAssembler(Protocol):
    """把节点组装为模型上下文的确定性组装器。"""

    @property
    def catalog(self) -> PromptCatalog: ...

    def assemble(
        self,
        tree: AgentTree,
        node_id: str,
        *,
        memory: MemorySnapshot | None = None,
    ) -> PromptAssembly: ...

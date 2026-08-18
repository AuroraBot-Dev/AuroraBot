"""由组合根构造的最小 AuroraBot 运行时。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import uuid4

from src.contracts import AgentTree

if TYPE_CHECKING:
    from aurora.configuration import RootAgentConfiguration
    from src.engine import AgentTreeRunner


@dataclass(frozen=True, slots=True)
class AuroraRuntime:
    """保留项目级构造边界，同时只运行 AgentTree 核心。"""

    runner: AgentTreeRunner
    root: RootAgentConfiguration

    def create_tree(self, message: str, *, tree_id: str | None = None) -> AgentTree:
        return AgentTree.create(
            tree_id or uuid4().hex,
            self.root.node_id,
            self.root.profile,
            self.root.model,
            message,
            tools=self.root.tools,
        )

    async def run(self, message: str, *, tree_id: str | None = None) -> AgentTree:
        return await self.runner.run(self.create_tree(message, tree_id=tree_id))

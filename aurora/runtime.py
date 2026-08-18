"""组合项目实例并提供 AuroraBot 运行入口。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import uuid4

from aurora.composition import compose_project
from aurora.composition.engine import ENGINE_RUNNER
from aurora.configuration.runtime import RUNTIME_CONFIG, RuntimeConfig
from src.contracts import AgentTree

if TYPE_CHECKING:
    from collections.abc import Iterable

    from aurora.config import AuroraConfig
    from src.contracts import Model, Tool
    from src.engine import AgentTreeRunner


@dataclass(frozen=True, slots=True)
class AuroraRuntime:
    """保留项目级构造边界，同时只运行 AgentTree 核心。"""

    runner: AgentTreeRunner
    root: RuntimeConfig

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


def assemble_runtime(config: AuroraConfig, model: Model, tools: Iterable[Tool] = ()) -> AuroraRuntime:
    """运行全部组件注册器，并取得完整运行时所需实例。"""
    assembly = compose_project(config, model, tools)
    return AuroraRuntime(assembly.get(ENGINE_RUNNER), config.get(RUNTIME_CONFIG))

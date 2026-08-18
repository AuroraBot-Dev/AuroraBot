"""组合项目实例并提供 AuroraBot 运行入口。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from aurora.composition import compose_project
from aurora.composition.engine import ENGINE_RUNNER
from aurora.configuration.runtime import RUNTIME_CONFIG, RuntimeConfig
from ops import ConfigAccess, ConfigSourceRef, OpsRuntime
from src.contracts import AgentNode, AgentTree, ChatMessage

if TYPE_CHECKING:
    from collections.abc import Iterable

    from aurora.config import AuroraConfig
    from src.contracts import Model, Tool
    from src.engine import AgentTreeRunner


@dataclass(slots=True)
class AuroraRuntime:
    """保留项目级构造边界，同时只运行 AgentTree 核心。"""

    runner: AgentTreeRunner
    root: RuntimeConfig
    config: AuroraConfig
    _trees: dict[str, AgentTree] = field(default_factory=dict, init=False, repr=False)
    ops: OpsRuntime = field(init=False)

    def __post_init__(self) -> None:
        sources = tuple(ConfigSourceRef(source.name, source.relative_path) for source in self.config.sources)
        self.ops = OpsRuntime(self, ConfigAccess(self.config.project_root, sources))

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
        tree = self.create_tree(message, tree_id=tree_id)
        if tree.tree_id in self._trees:
            raise ValueError(f"AgentTree 已存在：{tree.tree_id}")
        return await self.runner.run(tree, observer=self._record_tree)

    async def start_tree(self, message: str, *, tree_id: str | None = None) -> dict[str, Any]:
        return self._tree_dict(await self.run(message, tree_id=tree_id))

    def runtime_status(self) -> dict[str, Any]:
        statuses = {"running": 0, "completed": 0, "failed": 0}
        for tree in self._trees.values():
            statuses[tree.status.value] += 1
        return {"tree_count": len(self._trees), "trees": statuses}

    def list_trees(self, *, status: str | None = None, limit: int = 64) -> list[dict[str, Any]]:
        trees = reversed(tuple(self._trees.values()))
        return [self._tree_summary(tree) for tree in trees if status is None or tree.status.value == status][:limit]

    def tree_detail(self, tree_id: str) -> dict[str, Any] | None:
        tree = self._trees.get(tree_id)
        return self._tree_dict(tree) if tree is not None else None

    def node_detail(self, tree_id: str, node_id: str) -> dict[str, Any] | None:
        tree = self._trees.get(tree_id)
        if tree is None:
            return None
        try:
            node = tree.node(node_id)
        except KeyError:
            return None
        return self._node_dict(node)

    def _record_tree(self, tree: AgentTree) -> None:
        self._trees[tree.tree_id] = tree

    @staticmethod
    def _tree_summary(tree: AgentTree) -> dict[str, Any]:
        return {
            "tree_id": tree.tree_id,
            "root_id": tree.root_id,
            "status": tree.status.value,
            "node_count": len(tree.nodes),
        }

    @classmethod
    def _tree_dict(cls, tree: AgentTree) -> dict[str, Any]:
        return {**cls._tree_summary(tree), "nodes": [cls._node_dict(node) for node in tree.nodes]}

    @staticmethod
    def _node_dict(node: AgentNode) -> dict[str, Any]:
        return {
            "node_id": node.node_id,
            "parent_id": node.parent_id,
            "parent_call_id": node.parent_call_id,
            "profile_id": node.profile_id,
            "model": node.model,
            "tools": sorted(node.tools),
            "status": node.status.value,
            "result": node.result,
            "error": node.error,
            "messages": [AuroraRuntime._message_dict(message) for message in node.messages],
        }

    @staticmethod
    def _message_dict(message: ChatMessage) -> dict[str, Any]:
        return {
            "role": message.role,
            "content": message.content,
            "tool_call_id": message.tool_call_id,
            "is_error": message.is_error,
            "tool_calls": [
                {"call_id": call.call_id, "name": call.name, "arguments": dict(call.arguments)}
                for call in message.tool_calls
            ],
        }


def assemble_runtime(config: AuroraConfig, model: Model, tools: Iterable[Tool] = ()) -> AuroraRuntime:
    """运行全部组件注册器，并取得完整运行时所需实例。"""
    assembly = compose_project(config, model, tools)
    return AuroraRuntime(assembly.get(ENGINE_RUNNER), config.get(RUNTIME_CONFIG), config)

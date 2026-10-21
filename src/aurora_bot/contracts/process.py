"""Bot 认知过程的确定定义，运行实例仍由 AgentTree 表示。"""

import hashlib
import json
from dataclasses import dataclass, field

from aurora_bot.contracts.resource import ResourceKey, ResourceRef

TREE_PROCESS_KEY = ResourceKey("aurora", "engine", "process", "agent_tree")
TREE_PROCESS_MEDIA_TYPE = "application/vnd.aurora.agent-tree-process+json;version=1"


@dataclass(frozen=True, slots=True)
class TreeProcessDefinition:
    """认知循环的策略与上界，定义版本覆盖实际执行所用的完整声明。"""

    max_depth: int = 4
    max_nodes: int = 32
    max_steps: int = 256
    key: ResourceKey = TREE_PROCESS_KEY
    strategy: str = "depth_first"
    content: bytes = field(init=False, repr=False)
    ref: ResourceRef = field(init=False)

    def __post_init__(self) -> None:
        """过程属于 engine 领域，上界是正整数，策略名称必须明确。"""
        if self.key.domain != "engine" or self.key.kind != "process":
            raise ValueError("认知过程必须使用 namespace:engine/process/path 身份")
        if not self.strategy.strip():
            raise ValueError("认知过程必须声明执行策略")
        if any(type(value) is not int or value <= 0 for value in (self.max_depth, self.max_nodes, self.max_steps)):
            raise ValueError("认知过程运行上界必须为正整数")
        content = json.dumps(
            {
                "schema_version": 1,
                "key": str(self.key),
                "strategy": self.strategy,
                "max_depth": self.max_depth,
                "max_nodes": self.max_nodes,
                "max_steps": self.max_steps,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        object.__setattr__(self, "content", content)
        object.__setattr__(self, "ref", ResourceRef(self.key, hashlib.sha256(content).hexdigest()))


DEFAULT_TREE_PROCESS = TreeProcessDefinition()

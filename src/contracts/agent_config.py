"""Agent 配置与能力契约：限制、档案、引擎配置和能力描述符。"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Any


class _Msg(StrEnum):
    CAPABILITY_IDS_MUST_BE_UNIQUE = "capability IDs must be unique"


@dataclass(frozen=True, slots=True)
class CapabilityDescriptor:
    """Agent 能力的声明描述符，包含 ID、描述和参数 JSON Schema。"""

    id: str
    description: str
    parameters_schema: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class CapabilityCatalogSnapshot:
    """能力目录的快照，确保能力 ID 唯一。"""

    capabilities: tuple[CapabilityDescriptor, ...] = ()

    def __post_init__(self) -> None:
        identifiers = [item.id for item in self.capabilities]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError(_Msg.CAPABILITY_IDS_MUST_BE_UNIQUE)

    @property
    def by_id(self) -> MappingProxyType[str, CapabilityDescriptor]:
        return MappingProxyType({item.id: item for item in self.capabilities})

    def to_dict(self) -> dict[str, object]:
        return {"capabilities": [item.to_dict() for item in self.capabilities]}


@dataclass(frozen=True, slots=True)
class TaskLimits:
    """Task 的资源预算：最大模型调用数、最大工具调用数、最大持续时间。"""

    max_model_calls: int
    max_tool_calls: int
    max_duration_seconds: float


@dataclass(frozen=True, slots=True)
class AgentLimits:
    """Agent 运行时的并发与资源限制配置。"""

    root_profile: str = "builtin.root"
    worker_profile: str = "builtin.worker"
    max_active_agents: int = 16
    max_agents_per_task: int = 8
    max_depth: int = 3
    max_children_per_agent: int = 4
    turn_concurrency: int = 8
    model_concurrency: int = 4
    tool_concurrency: int = 8
    blocking_workers: int = 4
    lease_seconds: float = 30.0
    ambient_ttl_seconds: float = 1800.0


@dataclass(frozen=True, slots=True)
class AgentProfile:
    """Agent 配置档案：实现、模型角色、能力和委派权限。"""

    id: str
    implementation: str
    model_role: str
    capabilities: frozenset[str]
    can_delegate: bool
    child_profiles: frozenset[str]


@dataclass(frozen=True, slots=True)
class EngineConfiguration:
    """engine 启动配置：工作区、Agent 档案、限制和预算。"""

    workspace: str
    profiles: tuple[AgentProfile, ...]
    limits: AgentLimits
    interactive_budget: TaskLimits
    autonomous_budget: TaskLimits

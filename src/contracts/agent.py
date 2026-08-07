"""Agent 运行时核心契约：状态、决策、上下文、配置与跨层 Protocol。"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Literal, Protocol

from src.contracts.memory import MemoryContextSnapshot
from src.contracts.model import ToolDefinition
from src.contracts.triage import TriageLimits

if TYPE_CHECKING:
    from src.contracts.model import ModelRequest, ToolCall


# -- enums ---------------------------------------------------------------


class ErrorMsg(StrEnum):
    """Agent handler 或工具调用的错误码。"""

    AGENT_DECISION_REQUIRES_ONE_TRANSITION = "AgentDecision must contain exactly one atomic transition"
    CAPABILITY_IDS_MUST_BE_UNIQUE = "capability IDs must be unique"


class TaskStatus(StrEnum):
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    SILENT = "SILENT"
    CANCELLED = "CANCELLED"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    ERROR = "ERROR"


class AgentStatus(StrEnum):
    """Agent 持久化基态；等待语义由 activities/children 派生（RFC 0205）。"""

    READY = "READY"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class MessageStatus(StrEnum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    ERROR = "ERROR"


class ActivityStatus(StrEnum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    ERROR = "ERROR"
    CANCELLED = "CANCELLED"


# -- 配置类型 ------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CapabilityDescriptor:
    id: str
    description: str
    parameters_schema: dict[str, Any]
    runtime_completion: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class CapabilityCatalogSnapshot:
    capabilities: tuple[CapabilityDescriptor, ...] = ()

    def __post_init__(self) -> None:
        identifiers = [item.id for item in self.capabilities]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError(ErrorMsg.CAPABILITY_IDS_MUST_BE_UNIQUE)

    @property
    def by_id(self) -> MappingProxyType[str, CapabilityDescriptor]:
        return MappingProxyType({item.id: item for item in self.capabilities})

    def to_dict(self) -> dict[str, object]:
        return {"capabilities": [item.to_dict() for item in self.capabilities]}


@dataclass(frozen=True, slots=True)
class TaskLimits:
    max_model_calls: int
    max_tool_calls: int
    max_duration_seconds: float


@dataclass(frozen=True, slots=True)
class AgentLimits:
    root_profile: str = "builtin.triage"
    worker_profile: str = "builtin.worker"
    max_active_agents: int = 16
    max_agents_per_task: int = 8
    max_depth: int = 3
    max_children_per_agent: int = 4
    turn_concurrency: int = 8
    model_concurrency: int = 4
    tool_concurrency: int = 8
    blocking_workers: int = 4


@dataclass(frozen=True, slots=True)
class AgentProfile:
    id: str
    implementation: str
    model_role: str
    capabilities: frozenset[str]
    can_delegate: bool
    child_profiles: frozenset[str]
    triage_control: bool = False


@dataclass(frozen=True, slots=True)
class EngineConfiguration:
    workspace: str
    profiles: tuple[AgentProfile, ...]
    limits: AgentLimits
    interactive_budget: TaskLimits
    autonomous_budget: TaskLimits
    triage: TriageLimits


# -- Agent 动作 ----------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DelegationRequest:
    instruction: str
    profile_id: str | None = None


@dataclass(frozen=True, slots=True)
class ToolRequest:
    capability: str
    parameters: dict[str, Any]
    complete_task: bool = False
    tool_call_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ToolRequest":
        """从持久化的工具活动请求字典反序列化。"""
        return cls(
            capability=str(value["capability"]),
            parameters=dict(value.get("parameters", {})),
            complete_task=bool(value.get("complete_task", False)),
            tool_call_id=value.get("tool_call_id"),
        )


def capability_tool_definition(descriptor: CapabilityDescriptor) -> ToolDefinition:
    """保持外部 schema 原样，不再注入隐藏参数。"""
    return ToolDefinition(descriptor.id, descriptor.description, deepcopy(descriptor.parameters_schema))


@dataclass(frozen=True, slots=True)
class Completion:
    summary: str
    artifacts: tuple[dict[str, Any], ...] = ()
    silent: bool = False


@dataclass(frozen=True, slots=True)
class ChildResult:
    child_agent_id: str
    status: Literal["completed", "failed"]
    summary: str
    artifacts: tuple[dict[str, Any], ...] = ()
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# -- 运行时状态 ---------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TaskState:
    task_id: str
    root_agent_id: str
    root_message_id: str
    session_id: str
    root_summary: str
    autonomous: bool
    status: TaskStatus
    model_calls: int
    tool_calls: int
    max_model_calls: int
    max_tool_calls: int
    max_duration_seconds: float
    started_at: str
    updated_at: str
    termination_reason: str | None = None

    @property
    def terminal(self) -> bool:
        return self.status != TaskStatus.ACTIVE

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class AgentInstance:
    agent_id: str
    task_id: str
    parent_agent_id: str | None
    profile_id: str
    depth: int
    assignment: str
    status: AgentStatus
    state: dict[str, Any]
    created_at: str
    updated_at: str
    last_summary: str = ""

    @property
    def terminal(self) -> bool:
        return self.status in {AgentStatus.COMPLETED, AgentStatus.FAILED, AgentStatus.CANCELLED}

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class AgentMessage:
    message_id: str
    task_id: str
    target_agent_id: str
    type: str
    payload: dict[str, Any]
    causation_id: str | None
    correlation_id: str
    priority: int
    status: MessageStatus
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class AgentDecision:
    model_request: "ModelRequest | None" = None
    tool_request: ToolRequest | None = None
    delegations: tuple[DelegationRequest, ...] = ()
    completion: Completion | None = None
    wait_for_children: bool = False
    defer_seconds: float | None = None
    discard: bool = False
    failure: str | None = None
    state_patch: dict[str, Any] = field(default_factory=dict)
    memory_candidates: tuple[str, ...] = ()
    summary: str = ""

    def __post_init__(self) -> None:
        transitions = (
            self.model_request is not None,
            self.tool_request is not None,
            bool(self.delegations),
            self.completion is not None,
            self.wait_for_children,
            self.defer_seconds is not None,
            self.discard,
            self.failure is not None,
        )
        if sum(transitions) != 1:
            raise ValueError(ErrorMsg.AGENT_DECISION_REQUIRES_ONE_TRANSITION)

    def to_dict(self) -> dict[str, Any]:
        """将决策序列化为因果事件载荷。"""
        return {
            "model_request": self.model_request.to_dict() if self.model_request is not None else None,
            "tool_request": self.tool_request.to_dict() if self.tool_request is not None else None,
            "delegations": [asdict(item) for item in self.delegations],
            "completion": asdict(self.completion) if self.completion is not None else None,
            "wait_for_children": self.wait_for_children,
            "defer_seconds": self.defer_seconds,
            "discard": self.discard,
            "failure": self.failure,
            "state_patch": self.state_patch,
            "memory_candidates": list(self.memory_candidates),
            "summary": self.summary,
        }


@dataclass(frozen=True, slots=True)
class ActivityRequest:
    activity_id: str
    task_id: str
    agent_id: str
    kind: Literal["model", "tool"]
    request: dict[str, Any]
    status: ActivityStatus
    priority: int
    idempotency_key: str
    created_at: str


@dataclass(frozen=True, slots=True)
class ToolLease:
    activity_id: str
    task_id: str
    agent_id: str
    request_id: str
    session_id: str
    capability: str
    parameters: dict[str, Any]


@dataclass(frozen=True, slots=True)
class AgentContext:
    """一次 Agent 轮次的只读快照；handler 不得修改任何字段。"""

    task: TaskState
    agent: AgentInstance
    message: AgentMessage
    children: tuple[AgentInstance, ...]
    profile: AgentProfile
    capabilities: tuple[CapabilityDescriptor, ...]
    tool_definitions: tuple[ToolDefinition, ...] = ()
    memory: MemoryContextSnapshot = field(default_factory=MemoryContextSnapshot)
    pending_child_reports: bool = False


# -- Protocols ------------------------------------------------------------


class AgentHandler(Protocol):
    def handle(self, context: AgentContext) -> AgentDecision: ...


class Capability(Protocol):
    @property
    def tool_names(self) -> frozenset[str]: ...

    def tool_definitions(self, context: AgentContext) -> tuple["ToolDefinition", ...]: ...

    def handle_tool(self, call: "ToolCall") -> AgentDecision | None: ...

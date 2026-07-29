"""Agent 运行时核心契约：状态、决策、上下文、配置与跨层 Protocol。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Literal, Protocol

from src.contracts.memory import MemoryContextSnapshot
from src.contracts.triage import TriageLimits

if TYPE_CHECKING:
    from src.contracts.model import ModelContinuation, ToolCall, ToolDefinition


# -- enums ---------------------------------------------------------------


class ErrorMsg(StrEnum):
    """Agent handler 或工具调用的错误码。"""

    CAPABILITY_IDS_MUST_BE_UNIQUE = "capability IDs must be unique"
    AGENTDECISION_MUST_CONTAIN_EXACTLY_ONE_PRIMARY_ACTION = "AgentDecision must contain exactly one primary action"


class TaskStatus(StrEnum):
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    SILENT = "SILENT"
    CANCELLED = "CANCELLED"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    ERROR = "ERROR"


class AgentStatus(StrEnum):
    READY = "READY"
    WAITING_MODEL = "WAITING_MODEL"
    WAITING_TOOL = "WAITING_TOOL"
    WAITING_CHILDREN = "WAITING_CHILDREN"
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


@dataclass(frozen=True, slots=True)
class AgentProfile:
    id: str
    implementation: str
    model_role: str
    capabilities: frozenset[str]
    can_delegate: bool
    child_profiles: frozenset[str]


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
    continuation: dict[str, Any] | None = None


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
    revision: int
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
    available_at: str
    lease_until: str | None
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class AgentDecision:
    model_request: dict[str, Any] | None = None
    tool_request: ToolRequest | None = None
    delegations: tuple[DelegationRequest, ...] = ()
    completion: Completion | None = None
    wait_for_children: bool = False
    failure: str | None = None
    state_patch: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        actions = sum(
            (
                self.model_request is not None,
                self.tool_request is not None,
                bool(self.delegations),
                self.completion is not None,
                self.wait_for_children,
                self.failure is not None,
            )
        )
        if actions != 1:
            raise ValueError(ErrorMsg.AGENTDECISION_MUST_CONTAIN_EXACTLY_ONE_PRIMARY_ACTION)


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
    lease_until: str | None
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
    task: TaskState
    agent: AgentInstance
    message: AgentMessage
    children: tuple[AgentInstance, ...]
    profile: AgentProfile
    capabilities: tuple[CapabilityDescriptor, ...]
    memory: MemoryContextSnapshot = field(default_factory=MemoryContextSnapshot)


# -- Protocols ------------------------------------------------------------


class AgentHandler(Protocol):
    def handle(self, context: AgentContext) -> AgentDecision: ...


class Capability(Protocol):
    @property
    def tool_names(self) -> frozenset[str]: ...

    def tool_definitions(self, context: AgentContext) -> tuple["ToolDefinition", ...]: ...

    def handle_tool(
        self,
        call: "ToolCall",
        context: AgentContext,
        continuation: "ModelContinuation | None" = None,
        tools: tuple["ToolDefinition", ...] = (),
    ) -> AgentDecision | None: ...


class ToolQueue(Protocol):
    async def claim_tool_requests(self) -> tuple[ToolLease, ...]: ...
    async def tool_recovery_requests(self) -> tuple[ToolLease, ...]: ...


class ModelActivityQueue(Protocol):
    async def claim_model_requests(self, limit: int) -> tuple[ActivityRequest, ...]: ...
    async def complete_model(
        self, activity: ActivityRequest, result: dict[str, Any] | None, error: str | None
    ) -> None: ...

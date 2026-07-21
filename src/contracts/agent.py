"""Provider-neutral contracts for the RFC 0012 durable Agent runtime."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Literal, Protocol


class TaskStatus(StrEnum):
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    SILENT = "SILENT"
    CANCELLED = "CANCELLED"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    ERROR = "ERROR"


class AgentStatus(StrEnum):
    READY = "READY"
    RUNNING = "RUNNING"
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
            raise ValueError("capability IDs must be unique")

    @property
    def by_id(self) -> MappingProxyType[str, CapabilityDescriptor]:
        return MappingProxyType({item.id: item for item in self.capabilities})

    def to_dict(self) -> dict[str, object]:
        return {"capabilities": [item.to_dict() for item in self.capabilities]}


@dataclass(frozen=True, slots=True)
class TaskBudget:
    max_model_calls: int
    max_tool_calls: int
    max_duration_seconds: float


@dataclass(frozen=True, slots=True)
class AgentLimits:
    root_profile: str = "builtin.gate"
    worker_profile: str = "builtin.worker"
    memory_agent_profile: str | None = None
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
    id: str
    implementation: str
    model_role: str
    prompt: str
    capabilities: frozenset[str]
    can_delegate: bool
    child_profiles: frozenset[str]


@dataclass(frozen=True, slots=True)
class KernelConfiguration:
    workspace: str
    soul_content: str
    soul_hash: str
    profiles: tuple[AgentProfile, ...]
    limits: AgentLimits
    interactive_budget: TaskBudget
    autonomous_budget: TaskBudget


@dataclass(slots=True)
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


@dataclass(slots=True)
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


@dataclass(frozen=True, slots=True)
class AgentDecision:
    model_request: dict[str, Any] | None = None
    tool_request: ToolRequest | None = None
    delegations: tuple[DelegationRequest, ...] = ()
    claims: tuple[str, ...] = ()
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
            raise ValueError("AgentDecision must contain exactly one primary action")


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
class BrainContextSnapshot:
    persona: dict[str, str]
    active_tasks: tuple[dict[str, Any], ...]
    active_agents: tuple[dict[str, Any], ...]
    ambient_situations: tuple[dict[str, Any], ...]
    generated_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class AgentContext:
    task: TaskState
    agent: AgentInstance
    message: AgentMessage
    children: tuple[AgentInstance, ...]
    profile: AgentProfile
    capabilities: tuple[CapabilityDescriptor, ...]
    brain: BrainContextSnapshot
    memory_agent_profile: str | None = None


class AgentHandler(Protocol):
    def handle(self, context: AgentContext) -> AgentDecision: ...


class ToolQueue(Protocol):
    async def claim_tool_requests(self) -> tuple[ToolLease, ...]: ...

    async def tool_recovery_requests(self) -> tuple[ToolLease, ...]: ...


class ModelActivityQueue(Protocol):
    async def claim_model_requests(self, limit: int) -> tuple[ActivityRequest, ...]: ...

    async def complete_model(
        self, activity: ActivityRequest, result: dict[str, Any] | None, error: str | None
    ) -> None: ...

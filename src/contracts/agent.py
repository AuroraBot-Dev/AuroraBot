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
    WAITING_EFFECT = "WAITING_EFFECT"
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


ResultMode = Literal["resume", "terminal"]
CapabilityKind = Literal["effect", "publication"]
PublicationOperation = Literal["reply", "relay", "proactive_send"]
PublicationCompletionMode = Literal["continue", "complete_on_success"]


@dataclass(frozen=True, slots=True)
class CapabilityDescriptor:
    id: str
    description: str
    parameters_schema: dict[str, Any]
    result_mode: ResultMode = "resume"
    kind: CapabilityKind = "effect"
    endpoint: str | None = None
    operation: PublicationOperation | None = None
    root_only: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class CapabilityCatalogSnapshot:
    capabilities: tuple[CapabilityDescriptor, ...] = ()

    def __post_init__(self) -> None:
        identifiers = [item.id for item in self.capabilities]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("capability IDs must be unique")
        if any(item.result_mode not in {"resume", "terminal"} for item in self.capabilities):
            raise ValueError("capability result_mode must be resume or terminal")
        for item in self.capabilities:
            if item.kind not in {"effect", "publication"}:
                raise ValueError("capability kind must be effect or publication")
            if item.kind == "publication":
                if not item.endpoint or item.operation not in {"reply", "relay", "proactive_send"}:
                    raise ValueError("publication capability requires endpoint and operation")
                if not item.root_only:
                    raise ValueError("publication capability must be root_only")
                if item.result_mode != "resume":
                    raise ValueError("publication capability does not use effect result_mode")
            elif item.endpoint is not None or item.operation is not None:
                raise ValueError("effect capability cannot declare a publication endpoint or operation")

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
    effect_concurrency: int = 8
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
    audience_ref: str = "system.local"
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
class EffectRequest:
    capability: str
    parameters: dict[str, Any]
    tool_call_id: str | None = None
    continuation: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class CommunicationContext:
    endpoint_id: str
    audience_ref: str
    external_event_id: str | None = None
    external_message_id: str | None = None
    conversation_ref: str | None = None
    actor_ref: str | None = None
    reply_route_ref: str | None = None
    authored_by_self: bool | None = None
    origin_delivery_id: str | None = None

    @classmethod
    def from_dict(cls, value: object, *, require_message_fields: bool = False) -> "CommunicationContext":
        if not isinstance(value, dict):
            raise TypeError("communication context must be an object")
        allowed = {
            "endpoint_id",
            "external_event_id",
            "external_message_id",
            "conversation_ref",
            "actor_ref",
            "audience_ref",
            "reply_route_ref",
            "authored_by_self",
            "origin_delivery_id",
        }
        if set(value) - allowed:
            raise ValueError("communication context contains unsupported fields")
        endpoint_id = value.get("endpoint_id")
        audience_ref = value.get("audience_ref")
        if not isinstance(endpoint_id, str) or not endpoint_id:
            raise ValueError("communication endpoint_id must be a non-empty string")
        if not isinstance(audience_ref, str) or not audience_ref:
            raise ValueError("communication audience_ref must be a non-empty string")
        optional: dict[str, Any] = {}
        string_fields = allowed - {"endpoint_id", "audience_ref", "authored_by_self"}
        for name in string_fields:
            item = value.get(name)
            if item is not None and (not isinstance(item, str) or not item):
                raise ValueError(f"communication {name} must be a non-empty string or null")
            optional[name] = item
        authored_by_self = value.get("authored_by_self")
        if authored_by_self is not None and not isinstance(authored_by_self, bool):
            raise ValueError("communication authored_by_self must be boolean or null")
        optional["authored_by_self"] = authored_by_self
        required_message_fields = string_fields - {"origin_delivery_id"}
        if require_message_fields and any(optional[name] is None for name in required_message_fields):
            raise ValueError("message.received communication context requires all fields")
        return cls(endpoint_id=endpoint_id, audience_ref=audience_ref, **optional)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class DestinationGrant:
    alias: str
    endpoint_id: str
    capability_id: str
    operation: Literal["relay", "proactive_send"]
    allowed_source_audiences: frozenset[str]
    target_audience_ref: str
    configuration_hash: str
    description: str = ""
    target_audience_label: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "alias": self.alias,
            "endpoint_id": self.endpoint_id,
            "capability_id": self.capability_id,
            "operation": self.operation,
            "allowed_source_audiences": sorted(self.allowed_source_audiences),
            "target_audience_ref": self.target_audience_ref,
            "configuration_hash": self.configuration_hash,
            "description": self.description,
            "target_audience_label": self.target_audience_label,
        }


@dataclass(frozen=True, slots=True)
class PublicationRequest:
    operation: PublicationOperation
    text: str
    completion_mode: PublicationCompletionMode
    route_ref: str | None = None
    destination: str | None = None
    reason: str | None = None
    tool_call_id: str | None = None
    continuation: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if self.operation not in {"reply", "relay", "proactive_send"}:
            raise ValueError("unsupported publication operation")
        if not self.text:
            raise ValueError("publication text must be non-empty")
        if self.completion_mode not in {"continue", "complete_on_success"}:
            raise ValueError("unsupported publication completion mode")
        if self.operation == "reply":
            if not self.route_ref or self.destination is not None:
                raise ValueError("reply publication requires route_ref and forbids destination")
        elif not self.destination or self.route_ref is not None:
            raise ValueError("relay/proactive publication requires destination and forbids route_ref")
        if self.operation == "proactive_send" and not self.reason:
            raise ValueError("proactive_send publication requires reason")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


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
    effect_request: EffectRequest | None = None
    publication_request: PublicationRequest | None = None
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
                self.effect_request is not None,
                self.publication_request is not None,
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
    kind: Literal["model", "effect", "publication"]
    request: dict[str, Any]
    status: ActivityStatus
    priority: int
    idempotency_key: str
    lease_until: str | None
    created_at: str


@dataclass(frozen=True, slots=True)
class EffectLease:
    activity_id: str
    task_id: str
    agent_id: str
    request_id: str
    session_id: str
    capability: str
    parameters: dict[str, Any]


@dataclass(frozen=True, slots=True)
class PublicationLease:
    activity_id: str
    task_id: str
    agent_id: str
    request_id: str
    capability: str
    endpoint_id: str
    operation: PublicationOperation
    text: str
    completion_mode: PublicationCompletionMode
    source_audience_ref: str
    target_audience_ref: str
    root_message_id: str
    route_ref: str | None = None
    destination: str | None = None
    reason: str | None = None
    tool_call_id: str | None = None
    continuation: dict[str, Any] | None = None
    source_endpoint_id: str | None = None
    source_external_event_id: str | None = None
    hop_count: int = 0
    configuration_hash: str = ""


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


class EffectQueue(Protocol):
    async def claim_effect_requests(self) -> tuple[EffectLease, ...]: ...


class ModelActivityQueue(Protocol):
    async def claim_model_requests(self, limit: int) -> tuple[ActivityRequest, ...]: ...

    async def complete_model(
        self, activity: ActivityRequest, result: dict[str, Any] | None, error: str | None
    ) -> None: ...

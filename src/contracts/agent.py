"""RFC 0012 持久化 Agent 运行时的协议中立契约。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Literal, Protocol

from src.contracts.memory import MemoryContextSnapshot

if TYPE_CHECKING:
    from src.contracts.model import ModelContinuation, ToolCall, ToolDefinition


class ErrorMsg(StrEnum):
    """Agent handler 或工具调用的错误码。"""

    CAPABILITY_IDS_MUST_BE_UNIQUE = "capability IDs must be unique"
    AGENTDECISION_MUST_CONTAIN_EXACTLY_ONE_PRIMARY_ACTION = "AgentDecision must contain exactly one primary action"


class TaskStatus(StrEnum):
    """Task 生命周期状态：活跃、已完成、静默、取消、预算耗尽、错误。"""

    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    SILENT = "SILENT"
    CANCELLED = "CANCELLED"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    ERROR = "ERROR"


class AgentStatus(StrEnum):
    """Agent 实例的生命周期状态。"""

    READY = "READY"
    WAITING_MODEL = "WAITING_MODEL"
    WAITING_TOOL = "WAITING_TOOL"
    WAITING_CHILDREN = "WAITING_CHILDREN"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class MessageStatus(StrEnum):
    """邮箱消息的处理状态。"""

    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    ERROR = "ERROR"


class ActivityStatus(StrEnum):
    """Activity（模型/工具调用）的执行状态。"""

    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    ERROR = "ERROR"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True, slots=True)
class CapabilityDescriptor:
    """Agent 能力的声明描述符，包含 ID、描述和参数 JSON Schema。

    CapabilityDescriptor object::

        {
            "id": "string",
            "description": "string",
            "parameters_schema": {"...": "..."}
        }

    """

    id: str
    description: str
    parameters_schema: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class CapabilityCatalogSnapshot:
    """能力目录的快照，确保能力 ID 唯一。

    CapabilityCatalogSnapshot object::

        {
            "capabilities": [CapabilityDescriptor, ...]
        }

    """

    capabilities: tuple[CapabilityDescriptor, ...] = ()

    def __post_init__(self) -> None:
        identifiers = [item.id for item in self.capabilities]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError(ErrorMsg.CAPABILITY_IDS_MUST_BE_UNIQUE)

    @property
    def by_id(self) -> MappingProxyType[str, CapabilityDescriptor]:
        """按 ID 索引的只读能力映射。"""
        return MappingProxyType({item.id: item for item in self.capabilities})

    def to_dict(self) -> dict[str, object]:
        return {"capabilities": [item.to_dict() for item in self.capabilities]}


@dataclass(frozen=True, slots=True)
class TaskBudget:
    """Task 的资源预算：最大模型调用数、最大工具调用数、最大持续时间。

    TaskBudget object::

        {
            "max_model_calls": 0,
            "max_tool_calls": 0,
            "max_duration_seconds": 0.0
        }

    """

    max_model_calls: int
    max_tool_calls: int
    max_duration_seconds: float


@dataclass(frozen=True, slots=True)
class AgentLimits:
    """Agent 运行时的并发与资源限制配置。

    AgentLimits object::

        {
            "root_profile": "builtin.root",
            "worker_profile": "builtin.worker",
            "max_active_agents": 16,
            "max_agents_per_task": 8,
            "max_depth": 3,
            "max_children_per_agent": 4,
            "turn_concurrency": 8,
            "model_concurrency": 4,
            "tool_concurrency": 8,
            "blocking_workers": 4,
            "lease_seconds": 30.0,
            "ambient_ttl_seconds": 1800.0
        }

    """

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
    """Agent 配置档案：实现、模型角色、能力和委派权限。

    AgentProfile object::

        {
            "id": "string",
            "implementation": "string",
            "model_role": "string",
            "capabilities": ["string", ...],
            "can_delegate": false,
            "child_profiles": ["string", ...]
        }

    """

    id: str
    implementation: str
    model_role: str
    capabilities: frozenset[str]
    can_delegate: bool
    child_profiles: frozenset[str]


@dataclass(frozen=True, slots=True)
class EngineConfiguration:
    """engine 启动配置：工作区、Agent 档案、限制和预算。

    EngineConfiguration object::

        {
            "workspace": "/path/to/workspace",
            "profiles": [AgentProfile, ...],
            "limits": AgentLimits,
            "interactive_budget": TaskBudget,
            "autonomous_budget": TaskBudget
        }

    """

    workspace: str
    profiles: tuple[AgentProfile, ...]
    limits: AgentLimits
    interactive_budget: TaskBudget
    autonomous_budget: TaskBudget


@dataclass(frozen=True, slots=True)
class TaskState:
    """Task 的持久化运行状态。

    TaskState object::

        {
            "task_id": "UUID",
            "root_agent_id": "UUID",
            "root_message_id": "UUID",
            "session_id": "string",
            "root_summary": "string",
            "autonomous": false,
            "status": "ACTIVE" | "COMPLETED" | "SILENT" | "CANCELLED" | "BUDGET_EXHAUSTED" | "ERROR",
            "model_calls": 0,
            "tool_calls": 0,
            "max_model_calls": 0,
            "max_tool_calls": 0,
            "max_duration_seconds": 0.0,
            "started_at": "ISO-8601",
            "updated_at": "ISO-8601",
            "termination_reason": "string" | null
        }

    """

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
        """Task 是否已终止（非 ACTIVE 状态）。"""
        return self.status != TaskStatus.ACTIVE

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class AgentInstance:
    """Agent 实例的持久化状态，包括层级深度、分配和当前摘要。

    AgentInstance object::

        {
            "agent_id": "UUID",
            "task_id": "UUID",
            "parent_agent_id": "UUID" | null,
            "profile_id": "string",
            "depth": 0,
            "assignment": "string",
            "status": "READY" | "WAITING_MODEL" | "WAITING_TOOL" | "WAITING_CHILDREN" | ... | "CANCELLED",
            "revision": 0,
            "state": {"...": "..."},
            "created_at": "ISO-8601",
            "updated_at": "ISO-8601",
            "last_summary": "string"
        }

    """

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
        """Agent 是否已终止（COMPLETED / FAILED / CANCELLED）。"""
        return self.status in {AgentStatus.COMPLETED, AgentStatus.FAILED, AgentStatus.CANCELLED}

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class AgentMessage:
    """Agent 邮箱中的消息，包含因果追踪和租约信息。

    AgentMessage object::

        {
            "message_id": "UUID",
            "task_id": "UUID",
            "target_agent_id": "UUID",
            "type": "string",
            "payload": {"...": "..."},
            "causation_id": "UUID" | null,
            "correlation_id": "UUID",
            "priority": 0,
            "status": "PENDING" | "PROCESSING" | "COMPLETED" | "ERROR",
            "available_at": "ISO-8601",
            "lease_until": "ISO-8601" | null,
            "created_at": "ISO-8601"
        }

    """

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
    """Agent 发出的委派请求。

    DelegationRequest object::

        {
            "instruction": "string",
            "profile_id": "string" | null
        }

    """

    instruction: str
    profile_id: str | None = None


@dataclass(frozen=True, slots=True)
class ToolRequest:
    """Agent 发出的工具调用请求。

    ToolRequest object::

        {
            "capability": "string",
            "parameters": {"...": "..."},
            "complete_task": false,
            "tool_call_id": "string" | null,
            "continuation": {"...": "..."} | null
        }

    """

    capability: str
    parameters: dict[str, Any]
    complete_task: bool = False
    tool_call_id: str | None = None
    continuation: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class Completion:
    """Agent 的完成声明：摘要、产出物和静默标记。

    Completion object::

        {
            "summary": "string",
            "artifacts": [{"...": "..."}, ...],
            "silent": false
        }

    """

    summary: str
    artifacts: tuple[dict[str, Any], ...] = ()
    silent: bool = False


@dataclass(frozen=True, slots=True)
class ChildResult:
    """子 Agent 完成后的结果报告。

    ChildResult object::

        {
            "child_agent_id": "UUID",
            "status": "completed" | "failed",
            "summary": "string",
            "artifacts": [{"...": "..."}, ...],
            "error": "string" | null
        }

    """

    child_agent_id: str
    status: Literal["completed", "failed"]
    summary: str
    artifacts: tuple[dict[str, Any], ...] = ()
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class AgentDecision:
    """Agent handler 的返回决策：仅包含一个主动作（模型请求 / 工具调用 / 委派 / 完成 / 等待 / 失败）。

    AgentDecision object::

        {
            "model_request": {"...": "..."} | null,
            "tool_request": ToolRequest | null,
            "delegations": [DelegationRequest, ...],
            "claims": ["string", ...],
            "completion": Completion | null,
            "wait_for_children": false,
            "failure": "string" | null,
            "state_patch": {"...": "..."}
        }

    """

    model_request: dict[str, Any] | None = None
    tool_request: ToolRequest | None = None
    delegations: tuple[DelegationRequest, ...] = ()
    claims: tuple[str, ...] = ()
    completion: Completion | None = None
    wait_for_children: bool = False
    failure: str | None = None
    state_patch: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # 确保仅含一个主动作
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
    """外部 Activity（模型推理或工具执行）的调度请求。

    ActivityRequest object::

        {
            "activity_id": "UUID",
            "task_id": "UUID",
            "agent_id": "UUID",
            "kind": "model" | "tool",
            "request": {"...": "..."},
            "status": "PENDING" | "PROCESSING" | "COMPLETED" | "ERROR" | "CANCELLED",
            "priority": 0,
            "idempotency_key": "string",
            "lease_until": "ISO-8601" | null,
            "created_at": "ISO-8601"
        }

    """

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
    """工具执行租约：绑定 Activity 到本地执行上下文。

    ToolLease object::

        {
            "activity_id": "UUID",
            "task_id": "UUID",
            "agent_id": "UUID",
            "request_id": "string",
            "session_id": "string",
            "capability": "string",
            "parameters": {"...": "..."}
        }

    """

    activity_id: str
    task_id: str
    agent_id: str
    request_id: str
    session_id: str
    capability: str
    parameters: dict[str, Any]


@dataclass(frozen=True, slots=True)
class BrainContextSnapshot:
    """Brain 模块提供的全局上下文快照：活跃 Task、Agent 和环境态势。

    BrainContextSnapshot object::

        {
            "active_tasks": [{"...": "..."}, ...],
            "active_agents": [{"...": "..."}, ...],
            "ambient_situations": [{"...": "..."}, ...],
            "generated_at": "ISO-8601"
        }

    """

    active_tasks: tuple[dict[str, Any], ...]
    active_agents: tuple[dict[str, Any], ...]
    ambient_situations: tuple[dict[str, Any], ...]
    generated_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class AgentContext:
    """Agent handler 的输入上下文：包含 Task、Agent 实例、消息、子 Agent、档案和 Brain 快照。

    AgentContext object::

        {
            "task": TaskState,
            "agent": AgentInstance,
            "message": AgentMessage,
            "children": [AgentInstance, ...],
            "profile": AgentProfile,
            "capabilities": [CapabilityDescriptor, ...],
            "brain": BrainContextSnapshot
        }

    """

    task: TaskState
    agent: AgentInstance
    message: AgentMessage
    children: tuple[AgentInstance, ...]
    profile: AgentProfile
    capabilities: tuple[CapabilityDescriptor, ...]
    brain: BrainContextSnapshot
    memory: MemoryContextSnapshot = field(default_factory=MemoryContextSnapshot)


class AgentHandler(Protocol):
    """Agent handler 协议：接收 AgentContext，返回 AgentDecision。"""

    def handle(self, context: AgentContext) -> AgentDecision: ...


class Capability(Protocol):
    """Bot 自身能力：声明工具、按上下文决定展示、处理模型工具调用。"""

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
    """工具队列协议：认领待执行的工具请求和恢复请求。"""

    async def claim_tool_requests(self) -> tuple[ToolLease, ...]: ...

    async def tool_recovery_requests(self) -> tuple[ToolLease, ...]: ...


class ModelActivityQueue(Protocol):
    """模型 Activity 队列协议：认领模型请求并回传结果。"""

    async def claim_model_requests(self, limit: int) -> tuple[ActivityRequest, ...]: ...

    async def complete_model(
        self,
        activity: ActivityRequest,
        result: dict[str, Any] | None,
        error: str | None,
    ) -> None: ...

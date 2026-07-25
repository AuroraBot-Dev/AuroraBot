"""Agent 运行时核心契约：状态、决策、上下文与跨层 Protocol。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Literal, Protocol

from src.contracts.agent_actions import ChildResult, Completion, DelegationRequest, ToolRequest
from src.contracts.agent_config import (
    AgentLimits,
    AgentProfile,
    CapabilityCatalogSnapshot,
    CapabilityDescriptor,
    EngineConfiguration,
    TaskLimits,
)
from src.contracts.memory import MemoryContextSnapshot

if TYPE_CHECKING:
    from src.contracts.model import ModelContinuation, ToolCall, ToolDefinition

# -- 所有公开类型统一重导出，保证兼容性 --
__all__ = [
    "ActivityRequest",
    "ActivityStatus",
    "AgentContext",
    "AgentDecision",
    "AgentHandler",
    "AgentInstance",
    "AgentLimits",
    "AgentMessage",
    "AgentProfile",
    "AgentStatus",
    "BrainContextSnapshot",
    "Capability",
    "CapabilityCatalogSnapshot",
    "CapabilityDescriptor",
    "ChildResult",
    "Completion",
    "DelegationRequest",
    "EngineConfiguration",
    "ErrorMsg",
    "MessageStatus",
    "ModelActivityQueue",
    "TaskLimits",
    "TaskState",
    "TaskStatus",
    "ToolLease",
    "ToolQueue",
    "ToolRequest",
]


class ErrorMsg(StrEnum):
    """Agent handler 或工具调用的错误码。"""

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
class TaskState:
    """Task 的持久化运行状态。"""

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
    """Agent 实例的持久化状态，包括层级深度、分配和当前摘要。"""

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
    """Agent 邮箱中的消息，包含因果追踪和租约信息。"""

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
    """Agent handler 的返回决策：仅含一个主动作（模型请求/工具/委派/完成/等待/失败）。"""

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
            raise ValueError(ErrorMsg.AGENTDECISION_MUST_CONTAIN_EXACTLY_ONE_PRIMARY_ACTION)


@dataclass(frozen=True, slots=True)
class ActivityRequest:
    """外部 Activity（模型推理或工具执行）的调度请求。"""

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
    """工具执行租约：绑定 Activity 到本地执行上下文。"""

    activity_id: str
    task_id: str
    agent_id: str
    request_id: str
    session_id: str
    capability: str
    parameters: dict[str, Any]


@dataclass(frozen=True, slots=True)
class BrainContextSnapshot:
    """Brain 模块提供的全局上下文快照：活跃 Task、Agent 和环境态势。"""

    active_tasks: tuple[dict[str, Any], ...]
    active_agents: tuple[dict[str, Any], ...]
    ambient_situations: tuple[dict[str, Any], ...]
    generated_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class AgentContext:
    """Agent handler 的输入上下文：Task、Agent、消息、子 Agent、档案和 Brain 快照。"""

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

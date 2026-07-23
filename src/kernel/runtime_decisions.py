"""Agent turn 决策处理与授权应用。

负责组装 Agent 上下文、调用 Agent handler，并将 AgentDecision
转换为对应的 Command 提交至仓库。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

from jsonschema import ValidationError, validate

from src.contracts.agent import (
    AgentContext,
    AgentDecision,
    AgentInstance,
    TaskState,
)
from src.kernel.commands import (
    CompleteCommand,
    DelegateCommand,
    FailCommand,
    ModelCommand,
    ToolCommand,
    WaitCommand,
)

if TYPE_CHECKING:
    from src.contracts.agent import (
        AgentHandler,
        AgentLimits,
        AgentProfile,
        BrainContextSnapshot,
        CapabilityCatalogSnapshot,
    )
    from src.kernel.store import SQLiteRuntimeStore


def _capability_allowed(capability: str, policies: frozenset[str]) -> bool:
    """检查给定能力是否在许可策略中允许。

    支持通配符 '*' 和前缀通配符 'namespace.*'。
    """
    return (
        "*" in policies
        or capability in policies
        or any(policy.endswith(".*") and capability.startswith(policy[:-1]) for policy in policies)
    )


def _build_limit_dict(limits: AgentLimits) -> dict[str, int]:
    """将内核限制配置以 dict 形式返回。"""
    return {
        "max_active_agents": limits.max_active_agents,
        "max_agents_per_task": limits.max_agents_per_task,
        "max_depth": limits.max_depth,
        "max_children_per_agent": limits.max_children_per_agent,
    }


class DecisionKernel(Protocol):
    """决策处理所需的内核最小接口。"""

    _profiles: dict[str, AgentProfile]
    _handlers: dict[str, AgentHandler]
    store: SQLiteRuntimeStore

    @property
    def limits(self) -> AgentLimits: ...

    @property
    def capability_catalog(self) -> CapabilityCatalogSnapshot: ...

    def brain_context(self) -> BrainContextSnapshot: ...


def handle_claim(kernel: DecisionKernel, claim: tuple[Any, AgentInstance, TaskState]) -> AgentDecision:
    """组装 Agent 上下文并调用对应 profile 的 handler。"""
    message, agent, task = claim
    profile = kernel._profiles[agent.profile_id]
    descriptors = tuple(
        descriptor
        for descriptor in kernel.capability_catalog.capabilities
        if _capability_allowed(descriptor.id, profile.capabilities)
    )
    context = AgentContext(
        task=task,
        agent=agent,
        message=message,
        children=kernel.store.children(agent.agent_id),
        profile=profile,
        capabilities=descriptors,
        brain=kernel.brain_context(),
    )
    return kernel._handlers[agent.profile_id].handle(context)


def apply_failure(kernel: DecisionKernel, message: Any, agent: AgentInstance, error: str) -> None:
    """Agent turn 异常时的兜底处理：构造 FailCommand 并应用。"""
    command = FailCommand(summary=error, error=error)
    kernel.store.apply_decision(
        message=message,
        agent=agent,
        command=command,
        state_patch={},
        limits=_build_limit_dict(kernel.limits),
        priority=message.priority,
    )


def apply_authorized_decision(
    kernel: DecisionKernel, message: Any, agent: AgentInstance, decision: AgentDecision
) -> None:
    """校验 Agent 决策权限并构造对应 Command 提交至仓库。

    按优先级判断决策类型：
    1. model_request → ModelCommand（校验 model_role）
    2. tool_request → ToolCommand（校验 capability 权限和参数 schema）
    3. delegations → DelegateCommand（校验委托权限和子 profile）
    4. completion → CompleteCommand
    5. wait_for_children → WaitCommand（需有活跃子 Agent）
    6. failure → FailCommand
    任何不匹配将抛出 ValueError。
    """
    profile = kernel._profiles[agent.profile_id]
    claims = tuple(decision.claims)

    if decision.model_request is not None:
        command = _apply_model_request(kernel, agent, decision, profile, claims)
    elif decision.tool_request is not None:
        command = _apply_tool_request(kernel, agent, decision, profile, claims)
    elif decision.delegations:
        command = _apply_delegations(kernel, agent, decision, profile, claims)
    elif decision.completion is not None:
        command = _apply_completion(decision, claims)
    elif decision.wait_for_children:
        command = _apply_wait(kernel, agent, claims)
    elif decision.failure is not None:
        command = _apply_failure_decision(decision, claims)
    else:
        raise ValueError("unsupported Agent decision")

    kernel.store.apply_decision(
        message=message,
        agent=agent,
        command=command,
        state_patch=decision.state_patch,
        limits=_build_limit_dict(kernel.limits),
        priority=message.priority,
    )


def _apply_model_request(
    _kernel: DecisionKernel,
    agent: AgentInstance,
    decision: AgentDecision,
    profile: AgentProfile,
    claims: tuple[Any, ...],
) -> ModelCommand:
    request_role = decision.model_request.get("role")  # type: ignore[union-attr]
    if request_role != profile.model_role:
        raise PermissionError(f"Agent {agent.agent_id} cannot request model role {request_role}")
    return ModelCommand(request=decision.model_request, claims=claims)  # type: ignore[arg-type]


def _apply_tool_request(
    kernel: DecisionKernel,
    agent: AgentInstance,
    decision: AgentDecision,
    profile: AgentProfile,
    claims: tuple[Any, ...],
) -> ToolCommand:
    assert decision.tool_request is not None
    tool = decision.tool_request
    if not _capability_allowed(tool.capability, profile.capabilities):
        raise PermissionError(f"Agent {agent.agent_id} cannot request {tool.capability}")
    descriptor = kernel.capability_catalog.by_id.get(tool.capability)
    if descriptor is None:
        raise ValueError(f"unknown Tool capability {tool.capability}")
    try:
        validate(tool.parameters, descriptor.parameters_schema)
    except ValidationError as error:
        raise ValueError(f"Tool parameters do not match {tool.capability}: {error.message}") from error
    task = kernel.store.get_task(agent.task_id)
    assert task is not None
    return ToolCommand(
        request={
            "capability": tool.capability,
            "parameters": tool.parameters,
            "complete_task": tool.complete_task,
            "tool_call_id": tool.tool_call_id,
            "continuation": tool.continuation,
            "session_id": task.session_id,
        },
        claims=claims,
    )


def _apply_delegations(
    kernel: DecisionKernel,
    _agent: AgentInstance,
    decision: AgentDecision,
    profile: AgentProfile,
    claims: tuple[Any, ...],
) -> DelegateCommand:
    if not profile.can_delegate:
        raise PermissionError(f"Agent profile {profile.id} cannot delegate")
    delegation_requests: list[dict[str, str]] = []
    for delegation in decision.delegations:
        child_profile = delegation.profile_id or kernel.limits.worker_profile
        if child_profile not in profile.child_profiles or child_profile not in kernel._profiles:
            raise PermissionError(f"Agent profile {profile.id} cannot create {child_profile}")
        delegation_requests.append({"instruction": delegation.instruction, "profile_id": child_profile})
    return DelegateCommand(requests=tuple(delegation_requests), claims=claims)


def _apply_completion(decision: AgentDecision, claims: tuple[Any, ...]) -> CompleteCommand:
    return CompleteCommand(
        summary=decision.completion.summary,  # type: ignore[union-attr]
        artifacts=decision.completion.artifacts,  # type: ignore[union-attr]
        silent=decision.completion.silent,  # type: ignore[union-attr]
        claims=claims,
    )


def _apply_wait(kernel: DecisionKernel, agent: AgentInstance, claims: tuple[Any, ...]) -> WaitCommand:
    active_child = any(not child.terminal for child in kernel.store.children(agent.agent_id))
    if not active_child and not kernel.store.has_pending_child_reports(agent.agent_id):
        raise ValueError("Agent cannot wait without active children")
    return WaitCommand(claims=claims)


def _apply_failure_decision(decision: AgentDecision, claims: tuple[Any, ...]) -> FailCommand:
    return FailCommand(summary=decision.failure, error=decision.failure, claims=claims)  # type: ignore[arg-type]

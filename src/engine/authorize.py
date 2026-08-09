"""Agent 决策的构造、授权与原子应用（拆包）。

从 runtime.py 拆出的纯函数集合：构造只读 AgentContext、按决策字段分派
授权校验、将已授权决策交给 store 原子执行。不持有任何运行时状态。
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from jsonschema import ValidationError, validate

from src.contracts import (
    AgentContext,
    AgentDecision,
    AgentInstance,
    AgentLimits,
    AgentMessage,
    AgentProfile,
    DelegationRequest,
    MemoryQuery,
    ModelRequest,
    TaskState,
    ToolRequest,
    TriageLimits,
    capability_tool_definition,
)

if TYPE_CHECKING:
    from src.engine.runtime import AgentEngine as EngineState


class _Msg(StrEnum):
    """本文件内所有用户或模型可见的硬编码文本。"""

    AGENT_MODEL_ROLE_DENIED = "Agent {agent_id} cannot request model role {role}"
    AGENT_TOOL_DENIED = "Agent {agent_id} cannot request {capability}"
    UNKNOWN_TOOL = "unknown Tool capability {capability}"
    TOOL_PARAMS_MISMATCH = "Tool parameters do not match {capability}: {message}"
    PROFILE_CANNOT_DELEGATE = "Agent profile {profile_id} cannot delegate"
    PROFILE_CANNOT_CREATE = "Agent profile {profile_id} cannot create {child_profile}"
    TRIAGE_CONTROL_DENIED = "Agent profile {profile_id} cannot issue triage transitions"


def _policy_matches(capability: str, policy: str) -> bool:
    return policy in ("*", capability) or (policy.endswith(".*") and capability.startswith(policy[:-1]))


def _capability_allowed(capability: str, policies: frozenset[str]) -> bool:
    """权限域匹配：`!` 前缀否定优先于 `*` 与前缀通配（排除语义）。"""
    if any(
        policy.startswith("!") and len(policy) > 1 and _policy_matches(capability, policy[1:]) for policy in policies
    ):
        return False
    return any(_policy_matches(capability, policy) for policy in policies if not policy.startswith("!"))


def _build_limit_dict(limits: AgentLimits) -> dict[str, Any]:
    return {
        "max_active_agents": limits.max_active_agents,
        "max_agents_per_task": limits.max_agents_per_task,
        "max_depth": limits.max_depth,
        "max_children_per_agent": limits.max_children_per_agent,
        "worker_profile": limits.worker_profile,
    }


def handle_claim(
    kernel: "EngineState",
    message: AgentMessage,
    agent: AgentInstance,
    task: TaskState,
) -> tuple[AgentDecision, str]:
    """构造只读 AgentContext 并调用对应 handler，返回 (决策, 授权的 profile_id)。

    task/agent/message/children 直接复用当轮新建的 store 对象，不做深拷贝；
    handler 违反只读契约的变异会以失败告终，不会静默损坏状态。
    profile 与 capability 描述符是跨轮共享的规范对象，必须拷贝，防止 handler
    通过变异 context 提权。返回的 profile_id 在 handler 运行前捕获，apply
    路径据此取规范 profile，篡改 agent.profile_id 无法重定向授权。
    """
    profile_id = agent.profile_id
    profile = deepcopy(kernel._profiles[profile_id])
    descriptors = deepcopy(
        tuple(
            descriptor
            for descriptor in kernel.capability_catalog.capabilities
            if _capability_allowed(descriptor.id, profile.capabilities)
        )
    )
    context = AgentContext(
        task=task,
        agent=agent,
        message=message,
        children=kernel.store.children(agent.agent_id),
        profile=profile,
        capabilities=descriptors,
        tool_definitions=tuple(capability_tool_definition(item) for item in descriptors),
        memory=kernel.recall_memory(MemoryQuery(task.root_summary, task.session_id)),
        pending_child_reports=kernel.store.has_pending_child_reports(agent.agent_id),
    )
    return kernel._handlers[profile_id].handle(context), profile_id


def apply_failure(kernel: "EngineState", message: Any, agent: AgentInstance, error: str) -> None:
    kernel.store.apply_decision(
        message=message,
        agent=agent,
        decision=AgentDecision(failure=error),
        state_patch={},
        limits=_build_limit_dict(kernel.limits),
        priority=message.priority,
    )


def apply_authorized_decision(
    kernel: "EngineState", message: Any, agent: AgentInstance, profile_id: str, decision: AgentDecision
) -> None:
    """按决策字段分派授权校验；校验通过后原样交给 store 原子执行。

    completion/wait/failure 无需额外授权；wait 的等待前提校验在 store
    事务内原子完成。所有 resource 上界校验仍由 store 事务内执行。
    defer/discard 由 triage_control profile 专属，defer 的秒数在授权时
    按 TriageLimits 钳制。
    """
    profile = kernel._profiles[profile_id]
    if decision.model_request is not None:
        _authorize_model(agent, profile, decision.model_request)
    elif decision.tool_request is not None:
        _authorize_tool(kernel, agent, profile, decision.tool_request)
    elif decision.delegations:
        _authorize_delegation(kernel, profile, decision.delegations)
    elif decision.defer_seconds is not None or decision.discard:
        decision = _authorize_triage(profile, decision, kernel.configuration.triage)
    kernel.store.apply_decision(
        message=message,
        agent=agent,
        decision=decision,
        state_patch=decision.state_patch,
        limits=_build_limit_dict(kernel.limits),
        priority=message.priority,
    )


def _authorize_model(agent: AgentInstance, profile: AgentProfile, request: ModelRequest) -> None:
    if request.role != profile.model_role:
        raise PermissionError(_Msg.AGENT_MODEL_ROLE_DENIED.format(agent_id=agent.agent_id, role=request.role))


def _authorize_tool(kernel: "EngineState", agent: AgentInstance, profile: AgentProfile, tool: ToolRequest) -> None:
    if not _capability_allowed(tool.capability, profile.capabilities):
        raise PermissionError(_Msg.AGENT_TOOL_DENIED.format(agent_id=agent.agent_id, capability=tool.capability))
    descriptor = kernel.capability_catalog.by_id.get(tool.capability)
    if descriptor is None:
        raise ValueError(_Msg.UNKNOWN_TOOL.format(capability=tool.capability))
    try:
        validate(tool.parameters, descriptor.parameters_schema)
    except ValidationError as error:
        raise ValueError(_Msg.TOOL_PARAMS_MISMATCH.format(capability=tool.capability, message=error.message)) from error


def _authorize_delegation(
    kernel: "EngineState", profile: AgentProfile, delegations: tuple[DelegationRequest, ...]
) -> None:
    if not profile.can_delegate:
        raise PermissionError(_Msg.PROFILE_CANNOT_DELEGATE.format(profile_id=profile.id))
    for delegation in delegations:
        child_profile = delegation.profile_id or kernel.limits.worker_profile
        if child_profile not in profile.child_profiles or child_profile not in kernel._profiles:
            raise PermissionError(_Msg.PROFILE_CANNOT_CREATE.format(profile_id=profile.id, child_profile=child_profile))


def _authorize_triage(profile: AgentProfile, decision: AgentDecision, limits: TriageLimits) -> AgentDecision:
    """defer/discard 仅限 triage_control profile；defer 秒数钳制到 TriageLimits 上下界。"""
    if not profile.triage_control:
        raise PermissionError(_Msg.TRIAGE_CONTROL_DENIED.format(profile_id=profile.id))
    if decision.defer_seconds is None:
        return decision
    clamped = min(max(decision.defer_seconds, limits.quiet_seconds), limits.max_defer_seconds)
    return replace(decision, defer_seconds=clamped)

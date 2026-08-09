"""BaseAgent — 所有 Agent 逻辑类的共享基类。

逻辑同构的代码化：模型请求装配、工具定义收集、Capability 调度与决策
工厂方法统一由基类提供；子类只实现 handle() 的 turn 路由。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import StrEnum
from typing import TYPE_CHECKING, Any, cast

from src.contracts import (
    AgentDecision,
    Completion,
    DelegationRequest,
    ModelBudget,
    ModelMessage,
    ModelRequest,
    ToolChoice,
    ToolDefinition,
)

if TYPE_CHECKING:
    from src.contracts.agent import AgentContext, Capability
    from src.contracts.model import ModelContinuation
    from src.prompt import PromptComposer


class _Msg(StrEnum):
    """本文件内所有用户或模型可见的硬编码文本。"""

    COMPOSER_ALREADY_INSTALLED = "prompt composer is already installed"
    COMPOSER_REQUIRED = "BaseAgent requires an installed PromptComposer for this operation"
    CAPABILITIES_ALREADY_INSTALLED = "capabilities are already installed"
    DUPLICATE_TOOL_IDS = "model Tool IDs must be unique: {duplicates}"


class BaseAgent(ABC):
    """Agent 逻辑类基类：上下文输入 → 决策输出，共享请求装配与决策工厂。"""

    def __init__(
        self,
        *,
        composer: "PromptComposer | None" = None,
        capabilities: tuple["Capability", ...] = (),
    ) -> None:
        self._composer = composer
        self._capabilities = capabilities
        self._dispatch: dict[str, "Capability"] = {}
        if capabilities:
            self._install_capabilities(capabilities)

    def install_prompt_composer(self, composer: "PromptComposer") -> None:
        """安装提示词装配器，仅可调用一次。"""
        if self._composer is not None:
            raise RuntimeError(_Msg.COMPOSER_ALREADY_INSTALLED)
        self._composer = composer

    def install_capabilities(self, capabilities: tuple["Capability", ...]) -> None:
        """安装额外 Capability，仅可调用一次。"""
        if self._capabilities or self._dispatch:
            raise RuntimeError(_Msg.CAPABILITIES_ALREADY_INSTALLED)
        self._install_capabilities(capabilities)

    def _install_capabilities(self, capabilities: tuple["Capability", ...]) -> None:
        """将 Capability 安装到内部调度表。"""
        self._capabilities = capabilities
        for cap in capabilities:
            self._dispatch.update(dict.fromkeys(cap.tool_names, cap))

    @abstractmethod
    def handle(self, context: "AgentContext") -> AgentDecision:
        """Agent 入口：根据消息类型路由到对应处理阶段。"""

    # -- 共享装配 ---------------------------------------------------------

    def _collect_tool_definitions(self, context: "AgentContext") -> tuple[ToolDefinition, ...]:
        """收集所有工具定义：预计算的运行时 Capability + 内建 Capability，并检查名称唯一性。"""
        tools: list[ToolDefinition] = list(context.tool_definitions)
        for cap in self._capabilities:
            tools.extend(cap.tool_definitions(context))
        names = [tool.name for tool in tools]
        if len(names) != len(set(names)):
            duplicates = sorted({name for name in names if names.count(name) > 1})
            raise ValueError(_Msg.DUPLICATE_TOOL_IDS.format(duplicates=duplicates))
        return tuple(tools)

    def _require_composer(self) -> "PromptComposer":
        """获取已安装的提示词装配器，未安装时抛出异常。"""
        if self._composer is None:
            raise RuntimeError(_Msg.COMPOSER_REQUIRED)
        return self._composer

    def _request_model(
        self,
        context: "AgentContext",
        *,
        messages: tuple[ModelMessage, ...] | None = None,
        tools: tuple[ToolDefinition, ...] | None = None,
        output_schema: dict[str, object] | None = None,
        budget: ModelBudget | None = None,
        tool_choice: ToolChoice | None = None,
        continuation: "ModelContinuation | None" = None,
    ) -> AgentDecision:
        """构造带基础字段的模型请求；缺省消息来自 composer，缺省工具来自上下文。"""
        if messages is None:
            messages = self._require_composer().request_messages(context)
        if tools is None:
            tools = self._collect_tool_definitions(context)
        optional: dict[str, object] = {}
        if output_schema is not None:
            optional["output_schema"] = output_schema
        if budget is not None:
            optional["budget"] = budget
        if tool_choice is not None:
            optional["tool_choice"] = tool_choice
        if continuation is not None:
            optional["continuation"] = continuation
        request = ModelRequest(
            role=context.profile.model_role,
            messages=messages,
            required_capabilities=frozenset({"chat", "tools"} if tools else {"chat"}),
            response_mode="normalized",
            tools=tools,
            parallel_tool_calls=True,
            cancel_policy="never",
            **cast("dict[str, Any]", optional),
        )
        return AgentDecision(model_request=request)

    # -- 决策工厂 ---------------------------------------------------------

    @staticmethod
    def _delegate(
        instructions: tuple[tuple[str, str | None], ...],
        *,
        memory_candidates: tuple[str, ...] = (),
        summary: str = "",
    ) -> AgentDecision:
        """委托决策：instructions 为 (指令, 目标 profile) 元组序列。"""
        return AgentDecision(
            delegations=tuple(DelegationRequest(instruction, profile_id) for instruction, profile_id in instructions),
            memory_candidates=memory_candidates,
            summary=summary,
        )

    @staticmethod
    def _complete(summary: str, *, silent: bool = False) -> AgentDecision:
        return AgentDecision(completion=Completion(summary, silent=silent))

    @staticmethod
    def _fail(error: str) -> AgentDecision:
        return AgentDecision(failure=error)

    @staticmethod
    def _wait(*, state_patch: dict[str, object] | None = None) -> AgentDecision:
        return AgentDecision(wait_for_children=True, state_patch=dict(state_patch or {}))

    @staticmethod
    def _defer(seconds: float, *, summary: str = "", memory_candidates: tuple[str, ...] = ()) -> AgentDecision:
        return AgentDecision(defer_seconds=seconds, summary=summary, memory_candidates=memory_candidates)

    @staticmethod
    def _discard(*, summary: str = "", memory_candidates: tuple[str, ...] = ()) -> AgentDecision:
        return AgentDecision(discard=True, summary=summary, memory_candidates=memory_candidates)

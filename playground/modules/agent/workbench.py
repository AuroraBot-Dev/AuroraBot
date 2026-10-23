"""独立 Agent 工作台；不依赖终端、JSON 协议、Bot 或预设场景。

依赖资源由注入方持有并释放。观察轨迹只记录元数据；正文通过显式 inspect/snapshot 读取。
真实依赖不提供自动重放，调用方可以直接使用 Run 的事件流和并发控制。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from aurora_agent import Agent, DefaultContextAssembler, ModelResponse, ToolDecision

if TYPE_CHECKING:
    from collections.abc import Iterable

    from aurora_agent import (
        ChatMessage,
        ContextAssembler,
        ContextInput,
        Model,
        ModelRequest,
        RunLimits,
        RunRequest,
        RunSnapshot,
        Tool,
        ToolCall,
        ToolContext,
        ToolOutput,
        ToolPolicy,
    )


@dataclass(frozen=True, slots=True)
class Observation:
    sequence: int
    boundary: str
    phase: str
    name: str
    call_id: str | None = None
    error_type: str | None = None
    decision: str | None = None


class Probe:
    """保存最近一次端口输入输出供显式检查；不将正文写入轨迹或进程日志。"""

    def __init__(self) -> None:
        self.trace: list[Observation] = []
        self.request: ModelRequest | None = None
        self.response: ModelResponse | None = None

    def emit(
        self,
        boundary: str,
        phase: str,
        name: str,
        *,
        call_id: str | None = None,
        error_type: str | None = None,
        decision: str | None = None,
    ) -> None:
        self.trace.append(Observation(len(self.trace) + 1, boundary, phase, name, call_id, error_type, decision))


class ObservedModel:
    def __init__(self, provider: Model, probe: Probe) -> None:
        self.provider, self.probe = provider, probe

    async def complete(self, request: ModelRequest) -> ModelResponse:
        self.probe.request, self.probe.response = request, None
        self.probe.emit("model", "started", request.model)
        try:
            response = await self.provider.complete(request)
        except BaseException as error:
            self.probe.emit("model", "failed", request.model, error_type=type(error).__name__)
            raise
        # 不让观察投影抢先访问错误返回值；端口类型仍由真实 Run 检查。
        self.probe.response = response if isinstance(response, ModelResponse) else None
        self.probe.emit("model", "completed", request.model)
        return response


class ObservedTool:
    def __init__(self, tool: Tool, probe: Probe) -> None:
        self.tool, self.probe = tool, probe
        self.definition = tool.definition

    async def execute(self, call: ToolCall, context: ToolContext) -> ToolOutput:
        self.probe.emit("tool", "started", call.name, call_id=call.call_id)
        try:
            output = await self.tool.execute(call, context)
        except BaseException as error:
            self.probe.emit("tool", "failed", call.name, call_id=call.call_id, error_type=type(error).__name__)
            raise
        self.probe.emit("tool", "completed", call.name, call_id=call.call_id)
        return output


class ObservedAssembler:
    def __init__(self, assembler: ContextAssembler, probe: Probe) -> None:
        self.assembler, self.probe = assembler, probe

    async def assemble(self, context: ContextInput) -> tuple[ChatMessage, ...]:
        name = type(self.assembler).__name__
        self.probe.emit("context", "started", name)
        try:
            messages = await self.assembler.assemble(context)
        except BaseException as error:
            self.probe.emit("context", "failed", name, error_type=type(error).__name__)
            raise
        self.probe.emit("context", "completed", name)
        return messages


class ObservedPolicy:
    def __init__(self, policy: ToolPolicy, probe: Probe) -> None:
        self.policy, self.probe = policy, probe

    async def before_tool(self, snapshot: RunSnapshot, call: ToolCall) -> ToolDecision:
        self.probe.emit("policy", "started", call.name, call_id=call.call_id)
        try:
            decision = await self.policy.before_tool(snapshot, call)
        except BaseException as error:
            self.probe.emit("policy", "failed", call.name, call_id=call.call_id, error_type=type(error).__name__)
            raise
        self.probe.emit(
            "policy",
            "completed",
            call.name,
            call_id=call.call_id,
            decision=decision.action.value if isinstance(decision, ToolDecision) else None,
        )
        return decision


class Workbench:
    """一次独立运行的装配与观察入口；所有推进语义由真实 Run 负责。"""

    def __init__(
        self,
        request: RunRequest,
        *,
        instructions: str,
        model: str,
        provider: Model,
        tools: Iterable[Tool] = (),
        assembler: ContextAssembler | None = None,
        policy: ToolPolicy | None = None,
        limits: RunLimits | None = None,
    ) -> None:
        self.probe = Probe()
        agent = Agent(
            instructions=instructions,
            model=model,
            provider=ObservedModel(provider, self.probe),
            tools=tuple(ObservedTool(tool, self.probe) for tool in tools),
            assembler=ObservedAssembler(assembler if assembler is not None else DefaultContextAssembler(), self.probe),
            policy=ObservedPolicy(policy, self.probe) if policy is not None else None,
            limits=limits,
        )
        self.run = agent.create(request)

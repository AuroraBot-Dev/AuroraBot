from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from aurora_agent import (
    CallStatus,
    ContextInput,
    ModelResponse,
    Run,
    RunSnapshot,
    ToolAction,
    ToolDecision,
    ToolEffectUnknownError,
)
from aurora_agent import (
    ChatMessage as AgentMessage,
)
from aurora_agent import (
    ModelRequest as AgentModelRequest,
)
from aurora_agent import (
    ToolCall as AgentCall,
)
from aurora_agent import (
    ToolContext as AgentToolContext,
)
from aurora_agent import (
    ToolDefinition as AgentToolDefinition,
)
from aurora_agent import (
    ToolOutput as AgentToolOutput,
)
from aurora_bot.contracts import ChatMessage, ModelRequest, ToolCall, ToolDefinition, ToolOutput, ToolStatus
from aurora_bot.contracts.memory import MemoryRequest
from aurora_bot.contracts.model import ToolContext

if TYPE_CHECKING:
    from aurora_bot.contracts.prompt import PromptAssembly
    from aurora_bot.engine.ledger import RunLedger
    from aurora_kernel import Context

PREFIX = "aurora:kernel/module/"


@dataclass(slots=True)
class RunSession:
    ctx: Context
    ledger: RunLedger
    run: Run | None = None
    assembly: PromptAssembly | None = None
    model_calls: int = 0
    input_evidence: dict[int, tuple[str, ...]] = field(default_factory=dict)
    tool_evidence: dict[str, tuple[str, ...]] = field(default_factory=dict)
    outputs: dict[str, ToolOutput] = field(default_factory=dict)
    executed: set[str] = field(default_factory=set)
    notified: set[str] = field(default_factory=set)

    async def assemble(self, context: ContextInput) -> tuple[AgentMessage, ...]:
        request = self.ledger.request
        memory = await self.ctx.acall(
            f"{PREFIX}memory:recall",
            MemoryRequest(
                query="\n".join(message.content for message in (context.messages[:1] + context.messages[-1:])),
                focus_goal_ids=request.focus_goal_ids,
                scopes=request.memory_scopes,
            ),
        )
        messages = tuple(self.message(message, index) for index, message in enumerate(context.messages))
        assembled = await self.ctx.acall(
            f"{PREFIX}prompt:assemble",
            self.ledger.definition.prompt_id,
            messages,
            memory=memory,
            tools=self.ledger.tools,
        )
        self.assembly = assembled
        return tuple(agent_message(message) for message in assembled.messages)

    async def complete(self, request: AgentModelRequest) -> ModelResponse:
        assert self.assembly is not None
        endpoint = self.ctx.call(f"{PREFIX}ai:resolve_endpoint", request.model)
        assembled = self.assembly
        bound = ModelRequest(
            endpoint,
            assembled.messages,
            self.ledger.tools,
            resources=(self.ledger.definition.ref, *assembled.resources),
        )
        index = self.model_calls
        await self.ledger.model_requested(index, bound, assembled.memory)
        self.model_calls += 1
        try:
            response = await self.ctx.acall(f"{PREFIX}ai:complete", bound)
            if not isinstance(response, ChatMessage) or response.role != "assistant":
                raise TypeError("模型必须返回 assistant 消息")
        except BaseException as error:
            await self.ledger.append(
                f"model:{index}:failed",
                "engine.model.failed",
                "模型调用未完成",
                {
                    "model": request.model,
                    "error_type": type(error).__name__,
                },
            )
            raise
        await self.ledger.append(
            f"model:{index}:completed",
            "engine.model.completed",
            "模型调用完成",
            {
                "model": request.model,
                "content_length": len(response.content),
                "tool_call_count": len(response.tool_calls),
            },
        )
        if not response.tool_calls:
            delta = await self.ledger.delta(f"model:{index}:world-delta")
            if delta is not None:
                content, evidence = delta
                assert self.run is not None
                snapshot = self.run.snapshot()
                self.input_evidence[len(snapshot.messages) + len(snapshot.queued_messages) + 1] = evidence
                self.run.append_message(content)
        return ModelResponse(agent_message(response))

    async def before_tool(self, snapshot: RunSnapshot, call: AgentCall) -> ToolDecision:
        if call.call_id in self.ledger.scopes:
            await self.ctx.acall(f"{PREFIX}engine:before_tool", snapshot.run_id, self.contextual(call))
            return ToolDecision()
        visible = {tool.name for tool in self.ledger.tools}
        calls = tuple(
            self.contextual(record.call)
            for record in snapshot.calls
            if record.status is CallStatus.PENDING and record.call.name in visible
        )
        scopes = {item.call_id: self.ctx.call(f"{PREFIX}tools:scopes_for", item) for item in calls}
        self.ledger.observations |= frozenset(scope for resolved in scopes.values() for scope in resolved.observe)
        delta = await self.ledger.delta(f"tool:{call.call_id}:world-delta", calls=calls)
        if delta is not None:
            content, evidence = delta
            for record in snapshot.calls:
                if record.status is CallStatus.PENDING:
                    self.tool_evidence[record.call.call_id] = evidence
            return ToolDecision(ToolAction.RECONSIDER, content)
        await self.ledger.seal(calls, scopes)
        await self.ctx.acall(f"{PREFIX}engine:before_tool", snapshot.run_id, self.contextual(call))
        return ToolDecision()

    def contextual(self, call: AgentCall) -> ToolCall:
        return ToolCall(
            call.call_id,
            call.name,
            call.arguments,
            ToolContext(self.ledger.bot_id, self.ledger.run_id, f"{self.ledger.run_id}:tool:{call.call_id}:requested"),
        )

    def message(self, message: AgentMessage, index: int) -> ChatMessage:
        evidence = ()
        if message.role == "message":
            evidence = self.input_evidence.get(index, ())
            if index == 0 and self.ledger.request.caused_by:
                evidence = (self.ledger.request.caused_by,)
        elif message.role == "tool" and message.tool_call_id is not None:
            output = self.outputs.get(message.tool_call_id)
            evidence = output.evidence_refs if output is not None else self.tool_evidence.get(message.tool_call_id, ())
        return ChatMessage(
            message.role,
            message.content,
            tuple(ToolCall(call.call_id, call.name, call.arguments) for call in message.tool_calls),
            message.tool_call_id,
            message.is_error,
            evidence,
        )

    async def record_calls(self, snapshot: RunSnapshot) -> None:
        states = {
            CallStatus.SUCCEEDED: ToolStatus.SUCCEEDED,
            CallStatus.FAILED: ToolStatus.FAILED,
            CallStatus.UNKNOWN: ToolStatus.UNKNOWN,
        }
        for record in snapshot.calls:
            if record.status in states:
                output = self.outputs.get(record.call.call_id) or ToolOutput(
                    record.output.content if record.output else "工具效果未知，需要核对",
                    states[record.status],
                    self.tool_evidence.get(record.call.call_id, ()),
                )
                await self.ledger.output(self.contextual(record.call), output)
                if record.call.call_id in self.executed and record.call.call_id not in self.notified:
                    self.notified.add(record.call.call_id)
                    await self.ctx.acall(
                        f"{PREFIX}engine:after_tool", snapshot.run_id, self.contextual(record.call), output
                    )
        if (
            snapshot.messages[-1].role == "tool"
            and self.ledger.scopes
            and not any(record.status is CallStatus.PENDING for record in snapshot.calls)
        ):
            self.ledger.reviewed = False


@dataclass(frozen=True, slots=True)
class BoundTool:
    session: RunSession
    source: ToolDefinition

    @property
    def definition(self) -> AgentToolDefinition:
        return AgentToolDefinition(self.source.name, self.source.description, self.source.parameters)

    async def execute(self, call: AgentCall, context: AgentToolContext) -> AgentToolOutput:
        session = self.session
        bound = session.contextual(call)
        session.executed.add(call.call_id)
        output = await session.ctx.acall(f"{PREFIX}tools:execute", bound)
        if not isinstance(output, ToolOutput):
            raise TypeError("工具必须返回 ToolOutput")
        session.outputs[call.call_id] = output
        if output.status is ToolStatus.UNKNOWN:
            raise ToolEffectUnknownError()
        return AgentToolOutput(output.content, output.is_error)


def agent_message(message: ChatMessage) -> AgentMessage:
    return AgentMessage(
        message.role,
        message.content,
        tuple(AgentCall(call.call_id, call.name, call.arguments) for call in message.tool_calls),
        message.tool_call_id,
        message.is_error,
    )

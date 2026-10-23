"""单执行者的 ReAct 循环；所有可见状态转换都发生在 await 边界之间。"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import TYPE_CHECKING

from jsonschema import Draft202012Validator
from referencing import Registry

from aurora_agent.context import check_context_budget
from aurora_agent.contracts import (
    ContextBudgetError,
    ContextInput,
    ModelError,
    ModelRequest,
    ModelResponse,
    ToolAction,
    ToolContext,
    ToolDecision,
    ToolEffectUnknownError,
    ToolExecutionError,
    ToolOutput,
    Usage,
)
from aurora_agent.data import mutable_json
from aurora_agent.messages import ChatMessage, validate_history
from aurora_agent.state import CallRecord, CallStatus, EventKind, RunEvent, RunResult, RunSnapshot, RunStats, RunStatus

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from aurora_agent.contracts import ContextAssembler, Model, RunLimits, Tool, ToolDefinition, ToolPolicy
    from aurora_agent.messages import ToolCall


class Run:
    """由 Agent.create 构造，在一个事件循环内驱动；服务对象由宿主负责并发安全。"""

    def __init__(
        self,
        *,
        run_id: str,
        instructions: str,
        model: str,
        provider: Model,
        tools: tuple[tuple[ToolDefinition, Tool], ...],
        assembler: ContextAssembler,
        policy: ToolPolicy | None,
        limits: RunLimits,
        messages: tuple[ChatMessage, ...],
    ) -> None:
        self._run_id = run_id
        self._instructions = instructions
        self._model = model
        self._provider = provider
        self._definitions = tuple(definition for definition, _ in tools)
        self._tools = {definition.name: tool for definition, tool in tools}
        self._validators = {
            definition.name: Draft202012Validator(mutable_json(definition.parameters), registry=Registry())
            for definition, _ in tools
        }
        self._assembler = assembler
        self._policy = policy
        self._limits = limits
        self._messages = messages
        self._queued: tuple[ChatMessage, ...] = ()
        self._calls: dict[str, CallRecord] = {}
        self._stats = RunStats()
        self._status = RunStatus.READY
        self._result: RunResult | None = None
        self._cancel_requested = False
        self._driving = False
        self._events: list[RunEvent] = []
        self._changed = asyncio.Event()
        self._emit(EventKind.CREATED)

    def snapshot(self) -> RunSnapshot:
        return RunSnapshot(
            self._run_id,
            self._status,
            self._messages,
            self._queued,
            tuple(self._calls.values()),
            self._stats,
            self._cancel_requested,
            self._result,
        )

    def append_message(self, content: str) -> None:
        """只排队外部输入；下次模型调用前且所有工具结果配对后按提交顺序交付。"""
        if self._status.terminal:
            raise RuntimeError("已结束的 Run 不能追加消息")
        message = ChatMessage.message(content)
        self._queued = (*self._queued, message)
        self._emit(EventKind.MESSAGE_QUEUED)

    def cancel(self) -> None:
        """协作式取消；等待已开始的调用返回，不撤销外部效果。"""
        if self._status.terminal or self._cancel_requested:
            return
        self._cancel_requested = True
        self._emit(EventKind.CANCEL_REQUESTED)
        if not self._driving:
            self._finish(RunStatus.CANCELLED, reason="宿主请求取消")

    async def events(self, *, after: int = 0) -> AsyncIterator[RunEvent]:
        """独立订阅游标；重放 sequence > after 的事件，结束时排空并退出。"""
        if after < 0 or after > len(self._events):
            raise ValueError("事件游标不在已有事件范围内")
        index = after
        while True:
            while index < len(self._events):
                event = self._events[index]
                index += 1
                yield event
            if self._status.terminal:
                return
            self._changed.clear()
            await self._changed.wait()

    async def step(self) -> RunSnapshot:
        """推进一次模型调用或处理一个工具调用；已结束时只返回快照。"""
        await self._drive(continuous=False)
        return self.snapshot()

    async def run(self) -> RunResult:
        await self._drive(continuous=True)
        assert self._result is not None
        return self._result

    async def _drive(self, *, continuous: bool) -> None:
        if self._driving:
            raise RuntimeError("同一个 Run 不能并发推进")
        if self._status.terminal:
            return
        self._driving = True
        self._status = RunStatus.RUNNING
        try:
            await self._advance()
            while continuous and not self._status.terminal:
                await self._advance()
        except asyncio.CancelledError:
            self._cancel_requested = True
            self._mark_unknown()
            self._finish(RunStatus.CANCELLED, reason="驱动任务被取消")
            raise
        except (ContextBudgetError, ModelError) as error:
            self._mark_unknown()
            self._finish(RunStatus.FAILED, reason=type(error).__name__)
        except Exception as error:
            # 未预期异常保留状态后继续抛出；不将潜在敏感的异常正文写入日志或事件。
            self._mark_unknown()
            self._finish(RunStatus.FAILED, reason=type(error).__name__)
            raise
        finally:
            self._driving = False

    async def _advance(self) -> None:
        if self._cancel_requested:
            self._finish(RunStatus.CANCELLED, reason="宿主请求取消")
            return
        pending = self._pending()
        if pending:
            await self._tool_step(pending[0])
        else:
            await self._model_step()
        if self._cancel_requested and not self._status.terminal:
            self._finish(RunStatus.CANCELLED, reason="宿主请求取消")

    async def _model_step(self) -> None:
        if self._stats.model_calls >= self._limits.max_model_calls:
            self._finish(RunStatus.LIMIT_REACHED, reason="达到模型调用次数上限")
            return
        queued = self._queued
        context = ContextInput(
            self._run_id, self._instructions, self._model, (*self._messages, *queued), self._definitions
        )
        messages = await self._assembler.assemble(context)
        if self._cancel_requested:
            return
        request = ModelRequest(self._model, messages, self._definitions)
        check_context_budget(request, self._limits.max_context_chars)
        self._apply_messages(queued)
        self._stats = replace(self._stats, model_calls=self._stats.model_calls + 1)
        self._emit(EventKind.MODEL_STARTED)
        response = await self._provider.complete(request)
        if not isinstance(response, ModelResponse):
            raise TypeError("模型适配器必须返回 ModelResponse")
        updated = (*self._messages, response.message)
        validate_history(updated, allow_pending=True)
        self._messages = updated
        self._add_usage(response.usage)
        self._emit(EventKind.MODEL_COMPLETED)
        for call in response.message.tool_calls:
            self._calls[call.call_id] = CallRecord(call)
            self._emit(EventKind.TOOL_PROPOSED, call.call_id)
        # 推理期间追加的消息必须获得下一轮处理机会，不能被本轮最终回答吞掉。
        if not response.message.tool_calls and not self._queued and not self._cancel_requested:
            self._finish(RunStatus.COMPLETED, output=response.message.content)

    async def _tool_step(self, call: ToolCall) -> None:
        if self._stats.tool_calls >= self._limits.max_tool_calls:
            self._finish(RunStatus.LIMIT_REACHED, reason="达到工具调用次数上限")
            return
        tool = self._tools.get(call.name)
        if tool is None:
            self._record_output(call, ToolOutput("此工具不在可用目录中", is_error=True))
            return
        validator = self._validators[call.name]
        if not validator.is_valid(mutable_json(call.arguments)):
            self._record_output(call, ToolOutput("工具参数不符合声明的 JSON Schema", is_error=True))
            return
        if not await self._allow_tool(call) or self._cancel_requested:
            return
        self._stats = replace(self._stats, tool_calls=self._stats.tool_calls + 1)
        self._calls[call.call_id] = CallRecord(call, CallStatus.RUNNING)
        self._emit(EventKind.TOOL_STARTED, call.call_id)
        try:
            output = await tool.execute(call, ToolContext(self._run_id, call.call_id))
        except ToolExecutionError:
            output = ToolOutput("工具确认执行失败", is_error=True)
        except ToolEffectUnknownError:
            self._mark_unknown()
            self._finish(RunStatus.FAILED, reason="工具效果未知，需要宿主核对")
            return
        if not isinstance(output, ToolOutput):
            raise TypeError("工具必须返回 ToolOutput")
        self._record_output(call, output)

    async def _allow_tool(self, call: ToolCall) -> bool:
        if self._policy is None:
            return True
        decision = await self._policy.before_tool(self.snapshot(), call)
        if not isinstance(decision, ToolDecision):
            raise TypeError("行动前策略必须返回 ToolDecision")
        if self._cancel_requested:
            return False
        if decision.action == ToolAction.ALLOW:
            return True
        targets = self._pending() if decision.action == ToolAction.RECONSIDER else (call,)
        for target in targets:
            self._record_output(target, ToolOutput(decision.content, is_error=True))
        return False

    def _pending(self) -> tuple[ToolCall, ...]:
        return tuple(record.call for record in self._calls.values() if record.status == CallStatus.PENDING)

    def _record_output(self, call: ToolCall, output: ToolOutput) -> None:
        status = CallStatus.FAILED if output.is_error else CallStatus.SUCCEEDED
        self._calls[call.call_id] = CallRecord(call, status, output)
        self._messages = (*self._messages, ChatMessage.tool(call.call_id, output.content, is_error=output.is_error))
        self._emit(EventKind.TOOL_COMPLETED, call.call_id)

    def _mark_unknown(self) -> None:
        for call_id, record in tuple(self._calls.items()):
            if record.status == CallStatus.RUNNING:
                self._calls[call_id] = replace(record, status=CallStatus.UNKNOWN)
                self._emit(EventKind.TOOL_UNKNOWN, call_id)

    def _apply_messages(self, queued: tuple[ChatMessage, ...]) -> None:
        # 装配与预算通过后才确认交付；装配等待期间的新输入留给下一轮。
        if queued:
            self._messages = (*self._messages, *queued)
            self._queued = self._queued[len(queued) :]
            self._emit(EventKind.MESSAGES_APPLIED)

    def _add_usage(self, usage: Usage | None) -> None:
        if usage is not None:
            current = self._stats.usage or Usage()
            combined = Usage(current.input_tokens + usage.input_tokens, current.output_tokens + usage.output_tokens)
            self._stats = replace(self._stats, usage=combined)

    def _finish(self, status: RunStatus, *, output: str | None = None, reason: str | None = None) -> None:
        self._status = status
        self._result = RunResult(self._run_id, status, output, reason, self._stats)
        self._emit(EventKind.FINISHED)

    def _emit(self, kind: EventKind, call_id: str | None = None) -> None:
        self._events.append(RunEvent(len(self._events) + 1, self._run_id, kind, self._status, call_id))
        self._changed.set()

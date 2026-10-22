from __future__ import annotations

import asyncio

import pytest

from aurora_agent import (
    Agent,
    CallStatus,
    ChatMessage,
    ContextInput,
    ModelError,
    ModelRequest,
    ModelResponse,
    RunLimits,
    RunRequest,
    RunSnapshot,
    RunStatus,
    ToolAction,
    ToolCall,
    ToolContext,
    ToolDecision,
    ToolEffectUnknownError,
    ToolExecutionError,
    ToolOutput,
    Usage,
)
from tests.agent.support import EchoTool, ScriptedModel, echo_call


def test_react_steps_pair_tools_and_isolate_runs() -> None:
    async def scenario() -> None:
        tool = EchoTool()
        model = ScriptedModel(
            ModelResponse(ChatMessage.assistant(tool_calls=(echo_call(),)), Usage(10, 2)),
            ModelResponse(ChatMessage.assistant("已完成"), Usage(20, 4)),
        )
        agent = Agent(instructions="完成任务", model="fake/model", provider=model, tools=(tool,))
        run = agent.create(RunRequest("检查", run_id="first"))
        other = agent.create(RunRequest("另一任务", run_id="second"))
        initial = run.snapshot()
        assert initial.status == RunStatus.READY
        assert not model.requests and not tool.calls
        proposed = await run.step()
        assert proposed.calls[0].status == CallStatus.PENDING
        assert not tool.calls
        executed = await run.step()
        assert executed.calls[0].status == CallStatus.SUCCEEDED
        assert tool.calls[0][1] == ToolContext("first", "call-1")
        result = await run.run()
        assert result.status == RunStatus.COMPLETED
        assert result.output == "已完成"
        assert result.stats.usage == Usage(30, 6)
        assert result.stats.model_calls == len(model.requests)
        assert result.stats.tool_calls == 1
        assert [message.role for message in model.requests[1].messages] == ["system", "message", "assistant", "tool"]
        assert all(request.model == "fake/model" for request in model.requests)
        assert model.requests[0].tools == (tool.definition,)
        assert initial.calls == ()
        assert other.snapshot().status == RunStatus.READY
        assert (await run.run()) == result
        assert (await run.step()).result == result
        assert len(tool.calls) == 1

    asyncio.run(scenario())


@pytest.mark.parametrize("call", [ToolCall("bad", "hidden"), ToolCall("bad", "echo", {"text": 4})])
def test_unavailable_or_invalid_tool_cannot_produce_effects(call: ToolCall) -> None:
    tool = EchoTool()
    model = ScriptedModel(ChatMessage.assistant(tool_calls=(call,)), ChatMessage.assistant("修正完成"))
    run = Agent(instructions="处理", model="fake", provider=model, tools=(tool,)).create(RunRequest("执行"))
    result = asyncio.run(run.run())
    assert result.status == RunStatus.COMPLETED
    assert not tool.calls
    assert model.requests[1].messages[-1].is_error


@pytest.mark.parametrize(
    ("limits", "reason", "expected_models"),
    [
        (RunLimits(max_context_chars=1), "ContextBudgetError", 0),
        (RunLimits(max_tool_calls=0), "达到工具调用次数上限", 1),
        (RunLimits(max_model_calls=1), "达到模型调用次数上限", 1),
    ],
)
def test_limits_stop_before_the_next_effect(limits: RunLimits, reason: str, expected_models: int) -> None:
    tool = EchoTool()
    model = ScriptedModel(ChatMessage.assistant(tool_calls=(echo_call(),)))
    agent = Agent(instructions="处理", model="fake", provider=model, tools=(tool,), limits=limits)
    run = agent.create(RunRequest("执行"))
    result = asyncio.run(run.run())
    assert result.reason == reason
    assert len(model.requests) == expected_models
    assert len(tool.calls) == (1 if reason == "达到模型调用次数上限" else 0)


def test_tool_failure_is_observed_but_unknown_effect_stops_without_replay() -> None:
    class FailedTool(EchoTool):
        async def execute(self, call: ToolCall, context: ToolContext) -> ToolOutput:
            self.calls.append((call, context))
            raise ToolExecutionError("凭据不可写入事件")

    class UnknownTool(EchoTool):
        async def execute(self, call: ToolCall, context: ToolContext) -> ToolOutput:
            self.calls.append((call, context))
            raise ToolEffectUnknownError("连接中断，可能已写入")

    failed = FailedTool()
    model = ScriptedModel(ChatMessage.assistant(tool_calls=(echo_call(),)), ChatMessage.assistant("失败已处理"))
    run = Agent(instructions="处理", model="fake", provider=model, tools=(failed,)).create(RunRequest("执行"))
    assert asyncio.run(run.run()).status == RunStatus.COMPLETED
    assert model.requests[1].messages[-1].is_error

    unknown = UnknownTool()
    model = ScriptedModel(ChatMessage.assistant(tool_calls=(echo_call(),)))
    run = Agent(instructions="处理", model="fake", provider=model, tools=(unknown,)).create(RunRequest("执行"))
    result = asyncio.run(run.run())
    assert result.status == RunStatus.FAILED
    assert run.snapshot().calls[0].status == CallStatus.UNKNOWN
    assert run.snapshot().messages[-1].role == "assistant"
    assert asyncio.run(run.run()) == result
    assert len(unknown.calls) == 1


@pytest.mark.parametrize("action", [ToolAction.DENY, ToolAction.RECONSIDER])
def test_action_policy_controls_effects_and_preserves_pairing(action: ToolAction) -> None:
    class Policy:
        async def before_tool(self, snapshot: RunSnapshot, call: ToolCall) -> ToolDecision:
            assert snapshot.calls[0].call.call_id == "one"
            return ToolDecision(action, "环境已变化，请重新判断")

    calls = (echo_call("one"), echo_call("two"))
    tool = EchoTool()
    model = ScriptedModel(ChatMessage.assistant(tool_calls=calls), ChatMessage.assistant("已重新判断"))
    agent = Agent(instructions="处理", model="fake", provider=model, tools=(tool,), policy=Policy())
    run = agent.create(RunRequest("执行"))
    result = asyncio.run(run.run())
    assert result.status == RunStatus.COMPLETED
    assert not tool.calls
    assert [message.tool_call_id for message in model.requests[1].messages[-2:]] == ["one", "two"]
    assert all(message.is_error for message in model.requests[1].messages[-2:])


def test_custom_context_receives_snapshot_and_cannot_bypass_budget() -> None:
    class Assembler:
        async def assemble(self, context: ContextInput) -> tuple[ChatMessage, ...]:
            assert context.model == "fake"
            assert context.messages[-1].content == "执行"
            return (ChatMessage.system(context.instructions), *context.messages, ChatMessage.message("记忆" * 100))

    model = ScriptedModel()
    run = Agent(
        instructions="处理",
        model="fake",
        provider=model,
        assembler=Assembler(),
        limits=RunLimits(max_context_chars=100),
    ).create(RunRequest("执行"))
    assert asyncio.run(run.run()).reason == "ContextBudgetError"
    assert not model.requests


def test_model_error_has_terminal_result_without_sensitive_exception_text() -> None:
    class FailingModel:
        async def complete(self, request: ModelRequest) -> ModelResponse:
            raise ModelError("secret")

    run = Agent(instructions="处理", model="fake", provider=FailingModel()).create(RunRequest("执行"))
    result = asyncio.run(run.run())
    assert result.status == RunStatus.FAILED
    assert result.reason == "ModelError"


def test_duplicate_call_id_in_model_response_fails_before_tool_dispatch() -> None:
    tool = EchoTool()
    model = ScriptedModel(ChatMessage.assistant(tool_calls=(echo_call(),)))
    history = (ChatMessage.assistant(tool_calls=(echo_call(),)), ChatMessage.tool("call-1", "已有结果"))
    run = Agent(instructions="处理", model="fake", provider=model, tools=(tool,)).create(
        RunRequest("执行", history=history)
    )
    with pytest.raises(ValueError, match="不能重复"):
        asyncio.run(run.run())
    assert run.snapshot().status == RunStatus.FAILED
    assert not tool.calls

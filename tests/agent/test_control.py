from __future__ import annotations

import asyncio

import pytest

from aurora_agent import (
    Agent,
    CallStatus,
    ChatMessage,
    EventKind,
    ModelRequest,
    ModelResponse,
    RunLimits,
    RunRequest,
    RunStatus,
    ToolCall,
    ToolContext,
    ToolOutput,
)
from tests.agent.support import EchoTool, ScriptedModel, echo_call


def test_queued_inputs_wait_for_entire_tool_batch_and_keep_submission_order() -> None:
    async def scenario() -> None:
        entered = asyncio.Event()
        release = asyncio.Event()

        class BlockingTool(EchoTool):
            async def execute(self, call: ToolCall, context: ToolContext) -> ToolOutput:
                if call.call_id == "one":
                    entered.set()
                    await release.wait()
                return await super().execute(call, context)

        model = ScriptedModel(
            ChatMessage.assistant(tool_calls=(echo_call("one"), echo_call("two"))), ChatMessage.assistant("完成")
        )
        agent = Agent(instructions="处理", model="fake", provider=model, tools=(BlockingTool(),))
        run = agent.create(RunRequest("执行"))
        await run.step()
        run.append_message("第一条补充")
        driving = asyncio.create_task(run.step())
        await entered.wait()
        run.append_message("第二条补充")
        in_flight = run.snapshot()
        assert in_flight.messages[-1].role == "assistant"
        assert in_flight.calls[0].status == CallStatus.RUNNING
        with pytest.raises(RuntimeError, match="并发"):
            await run.run()
        release.set()
        await driving
        await run.step()
        assert tuple(message.content for message in run.snapshot().queued_messages) == ("第一条补充", "第二条补充")
        assert run.snapshot().messages[-1].tool_call_id == "two"
        assert (await run.run()).status == RunStatus.COMPLETED
        messages = model.requests[1].messages
        assert [message.role for message in messages] == [
            "system",
            "message",
            "assistant",
            "tool",
            "tool",
            "message",
            "message",
        ]
        assert [message.content for message in messages[-2:]] == ["第一条补充", "第二条补充"]
        assert tuple(message.content for message in in_flight.queued_messages) == ("第一条补充", "第二条补充")
        assert not run.snapshot().queued_messages
        with pytest.raises(RuntimeError, match="已结束"):
            run.append_message("太晚了")

    asyncio.run(scenario())


def test_input_during_model_call_gets_a_new_turn_instead_of_being_lost() -> None:
    async def scenario() -> None:
        entered = asyncio.Event()
        release = asyncio.Event()

        class BlockingModel(ScriptedModel):
            async def complete(self, request: ModelRequest) -> ModelResponse:
                if not self.requests:
                    entered.set()
                    await release.wait()
                return await super().complete(request)

        model = BlockingModel(ChatMessage.assistant("旧答案"), ChatMessage.assistant("新答案"))
        run = Agent(instructions="处理", model="fake", provider=model).create(RunRequest("执行"))
        driving = asyncio.create_task(run.run())
        await entered.wait()
        run.append_message("新条件")
        release.set()
        result = await driving
        assert result.output == "新答案"
        assert model.requests[1].messages[-1] == ChatMessage.message("新条件")
        assert model.requests[1].messages[-2] == ChatMessage.assistant("旧答案")

    asyncio.run(scenario())


def test_append_before_first_step_and_cancel_preserve_unconsumed_messages() -> None:
    model = ScriptedModel(ChatMessage.assistant("完成"))
    agent = Agent(instructions="处理", model="fake", provider=model)
    run = agent.create(RunRequest("执行"))
    run.append_message("补充")
    assert asyncio.run(run.run()).status == RunStatus.COMPLETED
    assert model.requests[0].messages[-1].content == "补充"
    cancelled = agent.create(RunRequest("取消任务"))
    cancelled.append_message("尚未处理")
    cancelled.cancel()
    assert asyncio.run(cancelled.run()).status == RunStatus.CANCELLED
    assert cancelled.snapshot().queued_messages[0].content == "尚未处理"
    assert len(model.requests) == 1


def test_budget_failure_keeps_queued_input_undelivered() -> None:
    model = ScriptedModel()
    agent = Agent(instructions="处理", model="fake", provider=model, limits=RunLimits(max_context_chars=1))
    run = agent.create(RunRequest("执行"))
    run.append_message("不能丢失的补充")
    result = asyncio.run(run.run())
    assert result.status == RunStatus.FAILED
    assert run.snapshot().queued_messages == (ChatMessage.message("不能丢失的补充"),)
    assert not model.requests


def test_late_input_stays_queued_when_no_model_turn_remains() -> None:
    async def scenario() -> None:
        entered = asyncio.Event()
        release = asyncio.Event()

        class BlockingModel(ScriptedModel):
            async def complete(self, request: ModelRequest) -> ModelResponse:
                entered.set()
                await release.wait()
                return await super().complete(request)

        model = BlockingModel(ChatMessage.assistant("本轮回答"))
        agent = Agent(instructions="处理", model="fake", provider=model, limits=RunLimits(max_model_calls=1))
        run = agent.create(RunRequest("执行"))
        driving = asyncio.create_task(run.run())
        await entered.wait()
        run.append_message("等待下一轮")
        release.set()
        assert (await driving).status == RunStatus.LIMIT_REACHED
        assert run.snapshot().queued_messages == (ChatMessage.message("等待下一轮"),)
        assert run.snapshot().messages[-1].content == "本轮回答"

    asyncio.run(scenario())


@pytest.mark.parametrize("force", [False, True])
def test_cancellation_during_tool_preserves_known_or_unknown_effect(force: bool) -> None:
    async def scenario() -> None:
        entered = asyncio.Event()
        release = asyncio.Event()

        class BlockingTool(EchoTool):
            async def execute(self, call: ToolCall, context: ToolContext) -> ToolOutput:
                self.calls.append((call, context))
                entered.set()
                await release.wait()
                return ToolOutput("已产生效果")

        tool = BlockingTool()
        model = ScriptedModel(ChatMessage.assistant(tool_calls=(echo_call("one"), echo_call("two"))))
        run = Agent(instructions="处理", model="fake", provider=model, tools=(tool,)).create(RunRequest("执行"))
        driving = asyncio.create_task(run.run())
        await entered.wait()
        if force:
            driving.cancel()
            with pytest.raises(asyncio.CancelledError):
                await driving
        else:
            run.cancel()
            assert run.snapshot().cancel_requested
            release.set()
            await driving
        snapshot = run.snapshot()
        assert snapshot.status == RunStatus.CANCELLED
        assert snapshot.calls[0].status == (CallStatus.UNKNOWN if force else CallStatus.SUCCEEDED)
        assert snapshot.calls[1].status == CallStatus.PENDING
        assert len(tool.calls) == 1
        await run.run()
        assert len(tool.calls) == 1

    asyncio.run(scenario())


def test_cancel_during_model_does_not_dispatch_proposed_tools() -> None:
    async def scenario() -> None:
        entered = asyncio.Event()
        release = asyncio.Event()

        class BlockingModel(ScriptedModel):
            async def complete(self, request: ModelRequest) -> ModelResponse:
                entered.set()
                await release.wait()
                return await super().complete(request)

        model = BlockingModel(ChatMessage.assistant(tool_calls=(echo_call(),)))
        tool = EchoTool()
        run = Agent(instructions="处理", model="fake", provider=model, tools=(tool,)).create(RunRequest("执行"))
        driving = asyncio.create_task(run.run())
        await entered.wait()
        run.cancel()
        release.set()
        assert (await driving).status == RunStatus.CANCELLED
        assert not tool.calls
        assert run.snapshot().calls[0].status == CallStatus.PENDING

    asyncio.run(scenario())


def test_event_subscribers_have_independent_cursors_and_finish_after_draining() -> None:
    async def scenario() -> None:
        model = ScriptedModel(ChatMessage.assistant(tool_calls=(echo_call(),)), ChatMessage.assistant("完成"))
        run = Agent(instructions="处理", model="fake", provider=model, tools=(EchoTool(),)).create(RunRequest("执行"))
        subscribed = asyncio.Event()

        async def observe() -> list[EventKind]:
            kinds = []
            async for event in run.events():
                kinds.append(event.kind)
                subscribed.set()
            return kinds

        observer = asyncio.create_task(observe())
        await subscribed.wait()
        await run.run()
        kinds = await observer
        replay = [event async for event in run.events()]
        tail = [event async for event in run.events(after=1)]
        assert kinds == [event.kind for event in replay]
        assert replay[1:] == tail
        assert [event.sequence for event in replay] == list(range(1, len(replay) + 1))
        assert kinds == [
            EventKind.CREATED,
            EventKind.MODEL_STARTED,
            EventKind.MODEL_COMPLETED,
            EventKind.TOOL_PROPOSED,
            EventKind.TOOL_STARTED,
            EventKind.TOOL_COMPLETED,
            EventKind.MODEL_STARTED,
            EventKind.MODEL_COMPLETED,
            EventKind.FINISHED,
        ]

    asyncio.run(scenario())

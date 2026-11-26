"""验证正式默认阶段的工具往返、失败观察、引导去重与中断接纳。"""

import asyncio
import json
from typing import cast

import pytest
from aurora_adapter.model import JsonValue, ModelProtocolError, ToolCall
from aurora_adapter.model.testing import FakeModel, FakeReply
from aurora_agent.model import ModelCall
from aurora_agent.model import plugin as model_plugin
from aurora_agent.react import ReActAgent
from aurora_agent.react import plugin as react_plugin
from aurora_agent.react_defaults import ReActContext, ReActDefaults
from aurora_agent.react_defaults import plugin as defaults_plugin
from aurora_agent.tools import TOOLS, ToolExecutor, ToolSpec
from aurora_agent.tools import plugin as tools_plugin
from aurora_control import ExecutionPlug, ExecutionRequest, InstanceStateBinding, StateBinding, component_entries
from aurora_core.bootstrap import bootstrap
from aurora_core.ctx import Context, StateKey
from aurora_core.discovery import register_plugins
from aurora_core.hooks import HookConnections
from aurora_core.ids import Id
from aurora_core.registry import RegistryEntry

STATE = Id("dev.defaults:state/data")
COMPONENT = Id("dev.defaults:handlers/compute")


@pytest.fixture
def factory():
    resources = []

    def create(respond, *, behavior="success", context_view=None):
        registry = bootstrap()
        register_plugins(registry, (react_plugin(), model_plugin(), tools_plugin(), defaults_plugin()))
        registry.register(RegistryEntry(STATE, "state_key", StateKey(), "test"))
        ctx, hooks = Context(registry), HookConnections(registry)
        client = FakeModel(respond)
        resources.append((ctx, hooks, client))

        def fixed(name):
            return InstanceStateBinding(STATE, (("name", name),))

        def transient(name):
            return StateBinding(STATE, (("name", name),))

        agent = ReActAgent(
            ctx,
            hooks,
            inbox=fixed("inbox"),
            progress=fixed("progress"),
            runtime=fixed("runtime"),
            batch=transient("batch"),
            decision=transient("decision"),
            max_iterations=5,
        )
        model = ModelCall(ctx, client, request_state=transient("request"), output_state=transient("response"))
        tools = ToolExecutor(
            ctx,
            registry,
            hooks,
            request_state=transient("calls"),
            output_state=transient("results"),
            current_state=transient("current"),
            timeout=10,
        )
        tool_input, tool_output = transient("input"), transient("output")
        calls, cleaned = [], []
        entered = asyncio.Event()

        async def compute(request):
            call = tool_input.get(ctx, request)
            assert isinstance(call, dict)
            calls.append(call)
            if behavior == "fail":
                raise ValueError("执行失败")
            if behavior == "wait" and call["id"] == "two":
                try:
                    entered.set()
                    await asyncio.Event().wait()
                finally:
                    cleaned.append(call["id"])
            tool_output.set(ctx, request, call["arguments"]["n"] * 2)

        registry.register_many(component_entries(COMPONENT, compute, compute, provider="test"))
        identity = Id("dev.defaults:tools/compute")
        registry.register(
            RegistryEntry(
                identity,
                "tool",
                ToolSpec(
                    COMPONENT,
                    {
                        "name": "compute",
                        "description": "数值翻倍",
                        "parameters": {
                            "type": "object",
                            "properties": {"n": {"type": "integer"}},
                            "required": ["n"],
                            "additionalProperties": False,
                        },
                    },
                ),
                "test",
                register_to=TOOLS,
            )
        )
        tools.connect(identity, ExecutionPlug(COMPONENT, compute, {"input": tool_input, "output": tool_output}))
        defaults = ReActDefaults(
            agent,
            model,
            tools,
            context_state=fixed("context"),
            system_prompt="自主判断是否需要行动",
            context_view=context_view,
        )
        defaults.connect()
        return ctx, agent, defaults, client, calls, entered, cleaned

    yield create
    for ctx, hooks, client in resources:
        asyncio.run(client.aclose())
        hooks.close()
        ctx.close()


def tool_call(
    identity: str = "one", *, name: str = "compute", arguments: dict[str, JsonValue] | None = None
) -> ToolCall:
    return {"id": identity, "name": name, "arguments": {"n": 3} if arguments is None else arguments}


def test_file_guidance_and_thinking_survive_tool_roundtrip_and_context_restore(factory):
    signed = {"type": "thinking", "thinking": "检查附件", "signature": "opaque-signature"}
    calls_seen = []

    def respond(request):
        calls_seen.append(request)
        return (
            FakeReply(tool_calls=(tool_call(),), reasoning=("检查", "附件"), thinking_blocks=(signed,))
            if len(calls_seen) == 1
            else FakeReply(("完成",), reasoning=("确认结果",))
        )

    ctx, agent, defaults, _client, _, _, _ = factory(respond)
    request = ExecutionRequest("files")
    content = [{"type": "image_url", "image_url": {"url": "data:image/png;base64,eA=="}}]
    agent.inbox.set(
        ctx, request, [{"id": "input-1", "sequence": 1, "payload": {"kind": "model_input", "content": content}}]
    )
    asyncio.run(agent.execute(request))
    assert calls_seen[0]["messages"][-1]["content"] == content
    assistant = next(item for item in calls_seen[1]["messages"] if item["role"] == "assistant")
    assert assistant["reasoning_content"] == "检查附件" and assistant["thinking_blocks"] == [signed]
    restored = json.loads(json.dumps(defaults._context(request)))
    assert restored["messages"][0]["content"] == content
    assert restored["messages"][1]["thinking_blocks"] == [signed]
    assert restored["messages"][-1]["reasoning_content"] == "确认结果"


@pytest.mark.parametrize("outcome", ["success", "fail", "unknown", "invalid"])
def test_tools_and_failures_return_to_model_as_observations(factory, outcome):
    def respond(request):
        if request["messages"][-1]["role"] == "tool":
            return FakeReply(("已经理解结果",))
        return FakeReply(
            tool_calls=(
                tool_call(
                    name="unknown" if outcome == "unknown" else "compute",
                    arguments={"n": "bad"} if outcome == "invalid" else None,
                ),
            )
        )

    ctx, agent, defaults, client, calls, _, _ = factory(respond, behavior="fail" if outcome == "fail" else "success")
    request = ExecutionRequest("run")
    asyncio.run(agent.execute(request))
    assert len(client.requests) == 2
    observation = json.loads(client.requests[-1]["messages"][-1]["content"])
    assert observation["status"] == ("completed" if outcome == "success" else "failed")
    assert len(calls) == (0 if outcome in ("unknown", "invalid") else 1)
    assert cast(dict, agent.runtime.get(ctx, request))["status"] == "completed"
    context = cast(ReActContext, defaults.context_state.get(ctx, request))
    assert context["pending"] is None and context["messages"][-1]["content"] == "已经理解结果"


def test_guidance_during_stream_is_seen_without_discarding_tools(factory):
    replies = []

    def respond(request):
        replies.append(request)
        return FakeReply(("准备",), tool_calls=(tool_call(),)) if len(replies) == 1 else FakeReply()

    ctx, agent, defaults, client, calls, _, _ = factory(respond)
    request = ExecutionRequest("run")
    initial = {"id": "first", "sequence": 1, "payload": "执行计算"}
    steer = {"id": "second", "sequence": 2, "payload": {"event": "保留计算结果"}}
    agent.inbox.set(ctx, request, [initial])
    injected = []

    def observe(change):
        if not injected and change.action == "set" and change.value.get("text") == "准备":
            injected.append(True)
            agent.inbox.set(ctx, request, [initial, steer])

    ctx.subscribe(observe, key=STATE, location=dict(defaults.model.output_state.address(request).location))
    asyncio.run(agent.execute(request))
    context = cast(ReActContext, defaults.context_state.get(ctx, request))
    assert context["guidance_sequence"] == agent.progress.get(ctx, request) == 2
    assert len(calls) == 1 and len(client.requests) == 2
    assert [row["role"] for row in context["messages"]] == ["user", "assistant", "tool", "user"]
    assert json.loads(context["messages"][-1]["content"]) == steer["payload"]
    asyncio.run(agent.execute(ExecutionRequest("again")))
    assert len(calls) == 1
    assert cast(ReActContext, defaults.context_state.get(ctx, request)) == context


def test_prepare_is_idempotent_when_context_was_saved_before_progress(factory):
    ctx, agent, defaults, _, _, _, _ = factory(lambda _: FakeReply())
    request = ExecutionRequest("run")
    incoming = [{"id": "first", "sequence": 1, "payload": "保持安静"}]
    agent.inbox.set(ctx, request, incoming)
    agent.batch.set(ctx, request, incoming)
    asyncio.run(defaults.build_prompt(request))
    asyncio.run(agent.execute(request))
    context = cast(ReActContext, defaults.context_state.get(ctx, request))
    assert context["messages"] == [{"role": "user", "content": "保持安静"}]
    assert agent.progress.get(ctx, request) == 1


def test_context_view_refreshes_without_changing_history_or_tool_pairs(factory):
    observations = ["初始观察"]
    boundaries = []

    def view(request):
        boundaries.append(request.run_id)
        return observations[-1]

    def respond(request):
        if len(boundaries) == 1:
            observations.append("推理期间到达的新观察")
            return FakeReply(tool_calls=(tool_call(),))
        return FakeReply(("完成",))

    ctx, agent, defaults, client, calls, _, _ = factory(respond, context_view=view)
    request = ExecutionRequest("run")
    agent.inbox.set(ctx, request, [{"id": "first", "sequence": 1, "payload": "执行计算"}])
    asyncio.run(agent.execute(request))
    assert boundaries == ["run", "run"] and len(calls) == 1
    first, second = [item["messages"] for item in client.requests]
    assert first[1] == {"role": "user", "content": "初始观察"}
    assert second[1] == {"role": "user", "content": "推理期间到达的新观察"}
    assert [message["role"] for message in second] == ["system", "user", "user", "assistant", "tool"]
    assert second[-2]["tool_calls"][0]["id"] == second[-1]["tool_call_id"] == "one"
    history = defaults.context_state.get(ctx, request)["messages"]
    assert [message["content"] for message in history if message["role"] == "user"] == ["执行计算"]
    asyncio.run(agent.execute(ExecutionRequest("again")))
    assert boundaries[-1] == "again" and len(calls) == 1
    assert sum(message["content"] == observations[-1] for message in client.requests[-1]["messages"]) == 1


def test_context_view_failure_retries_guidance_without_duplicate_history(factory):
    attempts = []

    def view(request):
        attempts.append(request.run_id)
        if len(attempts) == 1:
            raise ValueError("视图不可用")
        return "恢复后的观察"

    ctx, agent, defaults, client, _, _, _ = factory(lambda _: FakeReply(), context_view=view)
    request = ExecutionRequest("first")
    agent.inbox.set(ctx, request, [{"id": "guide", "sequence": 1, "payload": "继续"}])
    with pytest.raises(ValueError, match="视图不可用"):
        asyncio.run(agent.execute(request))
    assert not client.requests and len(agent.pending(request)) == 1
    asyncio.run(agent.execute(ExecutionRequest("retry")))
    history = defaults.context_state.get(ctx, request)["messages"]
    assert history == [{"role": "user", "content": "继续"}]
    assert agent.progress.get(ctx, request) == 1
    assert client.requests[0]["messages"][1]["content"] == "恢复后的观察"


def test_cancelled_batch_is_observed_next_time_without_reexecution(factory):
    responses = []

    def respond(request):
        responses.append(request)
        return (
            FakeReply(tool_calls=(tool_call("one"), tool_call("two"), tool_call("three")))
            if len(responses) == 1
            else FakeReply()
        )

    ctx, agent, defaults, client, calls, entered, cleaned = factory(respond, behavior="wait")
    request = ExecutionRequest("first")

    async def scenario():
        task = asyncio.create_task(agent.execute(request))
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert cast(ReActContext, defaults.context_state.get(ctx, request))["pending"] is not None
        await agent.execute(ExecutionRequest("next"))

    asyncio.run(scenario())
    assert [call["id"] for call in calls] == ["one", "two"] and cleaned == ["two"]
    messages = client.requests[-1]["messages"]
    results = [json.loads(row["content"]) for row in messages if row["role"] == "tool"]
    assert results[0]["value"] == 6
    assert [row["error"]["code"] for row in results[1:]] == ["cancelled", "not_executed"]
    assert cast(ReActContext, defaults.context_state.get(ctx, request))["pending"] is None


def test_missing_results_are_not_replaced_by_stale_batch(factory):
    ctx, agent, defaults, client, calls, _, _ = factory(lambda _: FakeReply())
    request = ExecutionRequest("next")
    defaults.context_state.set(
        ctx,
        request,
        {
            "messages": [],
            "guidance_sequence": 0,
            "pending": {
                "run_id": "previous",
                "turn_id": "expected",
                "message": {"role": "assistant", "content": "", "tool_calls": [tool_call()]},
            },
        },
    )
    defaults.tools.output_state.set(
        ctx,
        ExecutionRequest("previous"),
        {
            "turn_id": "stale",
            "status": "completed",
            "results": [{"call_id": "one", "name": "compute", "status": "completed", "value": 999}],
        },
    )
    asyncio.run(agent.execute(request))
    observation = json.loads(client.requests[-1]["messages"][-1]["content"])
    assert observation["error"]["code"] == "interrupted" and calls == []


@pytest.mark.parametrize("finish_reason", ["length", "content_filter"])
def test_incomplete_model_response_cannot_be_treated_as_success(factory, finish_reason):
    ctx, agent, defaults, _, calls, _, _ = factory(lambda _: FakeReply(("部分输出",), finish_reason=finish_reason))
    request = ExecutionRequest("run")
    with pytest.raises(ModelProtocolError):
        asyncio.run(agent.execute(request))
    assert calls == [] and cast(dict, agent.runtime.get(ctx, request))["status"] == "failed"
    assert defaults.context_state.get(ctx, request)["exchange_ends"] == []

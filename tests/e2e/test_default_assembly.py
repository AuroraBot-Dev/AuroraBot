"""验证 TOML 配置驱动的默认装配、运行期资源所有权与宿主关闭。"""

import asyncio
import json
from io import StringIO
from pathlib import Path
from typing import cast

import httpx
import pytest
import tomli_w
from aiohttp import ClientSession
from aurora_adapter.model import ChatCapabilities, JsonValue, ToolDefinition, UnsupportedCapability
from aurora_adapter.model.config import ADAPTERS, BINDINGS, ModelAdapter
from aurora_adapter.model.config import CONFIG as MODEL_CONFIG
from aurora_adapter.model.plugin import plugin as adapter_plugin
from aurora_adapter.model.testing import FakeModel, FakeReply
from aurora_agent.model import plugin as model_plugin
from aurora_agent.react import AgentBusyError
from aurora_agent.react import plugin as react_plugin
from aurora_agent.react_defaults import plugin as defaults_plugin
from aurora_agent.runtime import RunHandle, Submission
from aurora_agent.tools import TOOLS, ToolInstance, ToolSpec
from aurora_agent.tools import plugin as tools_plugin
from aurora_api.contract import describe_contract
from aurora_api.server import serve
from aurora_bot.assembly import ASSEMBLY, DefaultAssembly
from aurora_bot.assembly import plugin as assembly_plugin
from aurora_bot.assembly_config import AGENTS, CONFIG, RUN, WORK
from aurora_bot.conversation import CONVERSATION
from aurora_bot.conversation_contract import describe_conversation
from aurora_bot.operations import RUN_ACTIVATE, RUN_CANCEL, RUN_CONTROL, RUN_SUBMIT
from aurora_cli.commander import run_cli
from aurora_config import configuration_component
from aurora_config import plugin as configuration_plugin
from aurora_control import ExecutionPlug, ExecutionRequest, component_entries
from aurora_core.bootstrap import bootstrap
from aurora_core.ctx import Context
from aurora_core.discovery import Plugin, register_plugins
from aurora_core.hooks import HookConnections
from aurora_core.ids import Id
from aurora_core.invocation import invoke_operation
from aurora_core.lifecycle import Lifecycle, install_lifecycle_slots
from aurora_core.persistence import ContextPersistence
from aurora_core.registry import RegistryEntry
from aurora_core.storage import StorageService
from jsonschema import Draft202012Validator

ADAPTER = Id("dev.assembly:adapters/fake")
TOOL = Id("dev.assembly:tools/echo")
COMPONENT = Id("dev.assembly:handlers/echo")


@pytest.mark.parametrize("streaming,provider", [(False, "openai"), (True, "compatible")])
def test_litellm_default_assembly_tool_roundtrip_and_restore(tmp_path, monkeypatch, streaming, provider):
    monkeypatch.setenv("LITELLM_LOCAL_MODEL_COST_MAP", "True")
    from aurora_adapter.model.litellm import LiteLLMClient

    original = LiteLLMClient.__init__
    transports, requests = [], []

    def handle(request):
        value = json.loads(request.content)
        if provider == "compatible":
            assert request.url.host == "profile.test" and request.url.path == "/v1/chat/completions"
            assert value["model"] == "Qwen/custom-model"
            assert request.headers["authorization"] == "Bearer runtime-secret"
        assert value.get("stream", False) is streaming
        requests.append(value)
        observed = any(message["role"] == "tool" for message in value["messages"])
        message = {"role": "assistant", "content": "完成" if observed else None}
        if not observed:
            message["tool_calls"] = [
                {"id": "echo-1", "type": "function", "function": {"name": "echo", "arguments": '{"text":"你好"}'}}
            ]
        reason = "stop" if observed else "tool_calls"
        data = {
            "id": "test",
            "object": "chat.completion",
            "created": 1,
            "model": "gpt-4o-mini",
            "choices": [{"index": 0, "message": message, "finish_reason": reason}],
        }
        if not streaming:
            return httpx.Response(200, json=data)
        if not observed:
            message["tool_calls"][0]["index"] = 0
        data["object"] = "chat.completion.chunk"
        data["choices"] = [{"index": 0, "delta": message, "finish_reason": reason}]
        return httpx.Response(
            200,
            content=f"data: {json.dumps(data)}\n\ndata: [DONE]\n\n".encode(),
            headers={"content-type": "text/event-stream"},
        )

    def create_transport(self, config, **kwargs):
        original(self, config, transport=httpx.MockTransport(handle), **kwargs)
        transports.append(self._transport)

    monkeypatch.setattr(LiteLLMClient, "__init__", create_transport)

    async def scenario():
        host, assembly, ctx, _, _, _, _, _ = setup(tmp_path)

        def configure():
            ctx.set(CONFIG, {**settings(), "streaming": streaming})
            profile: dict[str, object] = {
                "adapter": "org.aurora.adapter:adapters/model/litellm/chat",
                "model": "openai/gpt-4o-mini",
                "credential": "MODEL_TEST_KEY",
            }
            if provider == "compatible":
                profile.update(
                    model="Qwen/custom-model",
                    provider="openai",
                    base_url="https://profile.test/v1",
                    capabilities={"streaming": True, "tool_calls": True},
                )
            ctx.set(
                MODEL_CONFIG,
                {"real": profile},
            )
            ctx.set(BINDINGS, {"reasoning": "real"})

        await host.start(configure=configure)
        try:
            assert requests == [] and assembly.agent is not None and assembly.defaults is not None
            execution = ExecutionRequest("sdk-roundtrip")
            assembly.agent.inbox.set(ctx, execution, [{"id": "guide", "sequence": 1, "payload": "回显你好"}])
            await host.run(assembly.activate, execution)
            messages = cast(dict, assembly.defaults.context_state.get(ctx, execution))["messages"]
            observed = next(message for message in messages if message["role"] == "tool")
            assert json.loads(observed["content"])["value"] == "工具:你好"
            assert messages[-1]["content"] == "完成" and len(requests) == 2
            assert cast(dict, assembly.agent.runtime.get(ctx, execution))["status"] == "completed"
            saved_profile = ctx.get(MODEL_CONFIG)
        finally:
            await host.stop()
        assert transports[0].is_closed
        assert "runtime-secret" not in (tmp_path / "framework" / "ctx.json").read_text(encoding="utf-8")
        restarted, other, other_ctx, _, _, _, _, _ = setup(tmp_path)
        await restarted.start()
        try:
            assert len(requests) == 2 and other.defaults is not None
            assert other_ctx.get(MODEL_CONFIG) == saved_profile
            assert cast(dict, other.defaults.context_state.get(other_ctx, execution))["messages"] == messages
        finally:
            await restarted.stop()
        assert len(transports) == 2 and all(transport.is_closed() for transport in transports)

    asyncio.run(scenario())


def settings(*, tools=True):
    return {
        "instance_id": "main",
        "model_role": "reasoning",
        "tools": [{"tool": str(TOOL), "instance_id": "echo", "config": {"prefix": "工具:"}}] if tools else [],
    }


def seed(ctx, *, tools=True, credential=False, model="first"):
    ctx.set(CONFIG, settings(tools=tools))
    profile = {"adapter": str(ADAPTER), "model": model}
    if credential:
        profile["credential"] = "MODEL_TEST_KEY"
    ctx.set(MODEL_CONFIG, {"primary": profile, "secondary": {"adapter": str(ADAPTER), "model": "second"}})
    ctx.set(BINDINGS, {"reasoning": "primary"})


def setup(
    root, *, behavior="normal", capabilities=None, secret="runtime-secret", extra_plugins=(), assembly_options=None
):
    registry = bootstrap()
    register_plugins(registry, (configuration_plugin(),))
    register_plugins(registry, extra_plugins)
    register_plugins(
        registry,
        (adapter_plugin(), model_plugin(), react_plugin(), tools_plugin(), defaults_plugin(), assembly_plugin()),
    )
    install_lifecycle_slots(registry)
    ctx, hooks = Context(registry), HookConnections(registry)
    events, clients, model_calls = [], [], []
    entered = asyncio.Event()
    close_attempts = []

    class Client(FakeModel):
        async def aclose(self):
            close_attempts.append("model")
            if behavior == "close_failure" and len(close_attempts) == 1:
                raise RuntimeError("模型关闭失败")
            await super().aclose()
            events.append("model.closed")

    async def model_factory(config, *, api_key=None):
        model_calls.append((config, api_key))
        events.append("model.created")

        def respond(request):
            if (
                behavior == "quiet"
                or not request.get("tools")
                or any(message["role"] == "tool" for message in request["messages"])
            ):
                return FakeReply((config.model,))
            return FakeReply(tool_calls=({"id": "echo-1", "name": "echo", "arguments": {"text": "你好"}},))

        client = Client(respond, capabilities=capabilities)
        clients.append(client)
        return client

    async def tool_factory(*, ctx, storage, instance_id, input_state, output_state, config):
        events.append("tool.created")

        async def execute(request):
            call = input_state.get(ctx, request)
            assert isinstance(call, dict)
            events.append("tool.executed")
            if behavior == "tool_failure":
                raise RuntimeError("验收工具失败")
            if behavior in ("wait", "tool_timeout"):
                try:
                    entered.set()
                    await asyncio.Event().wait()
                finally:
                    events.append("tool.cancelled")
            output_state.set(ctx, request, config["prefix"] + call["arguments"]["text"])

        async def close():
            events.append("tool.closed")
            storage.set("dev.assembly", "last_close", instance_id)
            ctx.set(AGENTS, "工具最后写入", location={"instance_id": "main", "part": "last_close"})

        return ToolInstance(
            ExecutionPlug(COMPONENT, execute, {"input": input_state, "output": output_state}, instance_id=instance_id),
            close,
        )

    async def placeholder(request):
        raise AssertionError("应调用工厂创建的实例")

    registry.register(
        RegistryEntry(ADAPTER, "adapter", ModelAdapter("chat", model_factory), "test", register_to=ADAPTERS)
    )
    registry.register_many(component_entries(COMPONENT, placeholder, placeholder, provider="test"))
    definition: ToolDefinition = {
        "name": "echo",
        "description": "回显",
        "parameters": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
            "additionalProperties": False,
        },
    }
    registry.register(
        RegistryEntry(TOOL, "tool", ToolSpec(COMPONENT, definition, factory=tool_factory), "test", register_to=TOOLS)
    )
    storage = StorageService(root)
    assembly = DefaultAssembly(
        registry=registry,
        ctx=ctx,
        hooks=hooks,
        storage=storage,
        credential_resolver=lambda _: secret,
        **(assembly_options or {}),
    )

    class ConfiguredLifecycle(Lifecycle):
        """将各用例声明的初始配置写入 TOML，供后续宿主从文件加载。"""

        async def start(self, *, configure=None):
            def configure_files():
                if configure is not None:
                    configure()
                    for key, relative in (
                        (CONFIG, "org.aurora.bot/config.toml"),
                        (MODEL_CONFIG, "org.aurora.adapter/model/profiles.toml"),
                        (BINDINGS, "org.aurora.adapter/model/bindings.toml"),
                    ):
                        path = root / "config" / relative
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_text(tomli_w.dumps(cast(dict, ctx.get(key))), encoding="utf-8")

            await super().start(configure=configure_files)

    host = ConfiguredLifecycle(
        ctx,
        hooks,
        (configuration_component(registry, ctx, hooks, storage), *assembly.components()),
        persistence=ContextPersistence(ctx, storage.snapshot_store()),
        storage=storage,
        timeout=0.05 if behavior == "wait" else 10,
    )
    return host, assembly, ctx, registry, clients, model_calls, events, entered


def test_factory_creation_follows_restore_and_configure_and_start_does_not_activate(tmp_path):
    async def scenario():
        host, assembly, ctx, _, clients, model_calls, events, _ = setup(tmp_path)
        assert events == [] and assembly.agent is None
        await host.start(configure=lambda: seed(ctx, credential=True))
        assert events == ["model.created", "tool.created"] and clients[0].requests == []
        assert model_calls[0][1] == "runtime-secret"
        assert assembly.agent is not None and assembly.defaults is not None
        request = ExecutionRequest("first")
        assembly.agent.inbox.set(ctx, request, [{"id": "event", "sequence": 1, "payload": "开始"}])
        await host.run(assembly.activate, request)
        messages = cast(dict, assembly.defaults.context_state.get(ctx, request))["messages"]
        observed = json.loads(next(message["content"] for message in messages if message["role"] == "tool"))
        assert observed["value"] == "工具:你好"
        await host.stop()
        assert events[-2:] == ["tool.closed", "model.closed"] and clients[0].closed
        snapshot = (tmp_path / "framework" / "ctx.json").read_text(encoding="utf-8")
        assert "runtime-secret" not in snapshot and "工具最后写入" in snapshot

        restored, other, other_ctx, _, new_clients, new_calls, _, _ = setup(tmp_path)
        await restored.start(configure=lambda: other_ctx.set(BINDINGS, {"reasoning": "secondary"}))
        assert new_calls[0][0].model == "second" and new_calls[0][1] is None
        assert new_clients[0] is not clients[0] and new_clients[0].requests == []
        assert other.agent is not None and other.defaults is not None
        assert cast(dict, other.defaults.context_state.get(other_ctx, request))["messages"] == messages
        assert other.agent.progress.get(other_ctx, request) == 1
        assert other.storage.get("dev.assembly", "last_close") == "main/tool/echo"
        assert other.defaults.model.output_state.get(other_ctx, request)
        await restored.stop()
        # 没有新激活的启动/关闭保留最近模型结果。
        saved = json.loads((tmp_path / "framework" / "ctx.json").read_text(encoding="utf-8"))
        assert any(entry["location"].get("part") == "model_output" for entry in saved["entries"])

    asyncio.run(scenario())


@pytest.mark.parametrize("identity", ["default", "default/model", "default/bot"])
@pytest.mark.parametrize("behavior", ["normal", "close_failure"])
def test_overlapping_instance_names_preserve_model_cleanup(tmp_path, identity, behavior, monkeypatch):
    async def scenario():
        host, assembly, ctx, _, clients, _, events, _ = setup(tmp_path, behavior=behavior)

        def configure():
            seed(ctx)
            ctx.set(CONFIG, {**cast(dict, ctx.get(CONFIG)), "instance_id": identity})

        store = assembly.storage.snapshot_store()
        original_save = type(store).save

        def save(store, snapshot):
            assert clients[0].closed
            events.append("snapshot.saved")
            original_save(store, snapshot)

        monkeypatch.setattr(type(store), "save", save)
        await host.start(configure=configure)
        if behavior == "close_failure":
            with pytest.raises(RuntimeError, match="模型关闭失败"):
                await host.stop()
            assert host.state == "failed" and not clients[0].closed
            assert "snapshot.saved" not in events
        await host.stop()
        assert host.state == "stopped" and clients[0].closed and assembly.client is None
        assert events[-3:] == ["tool.closed", "model.closed", "snapshot.saved"]
        assert events.count("tool.closed") == 1
        with pytest.raises(RuntimeError, match="关闭"):
            ctx.get(CONFIG)

    asyncio.run(scenario())


def test_shutdown_cancels_inflight_tool_before_closing_resources(tmp_path):
    async def scenario():
        host, assembly, ctx, _, clients, _, events, entered = setup(tmp_path, behavior="wait")
        await host.start(configure=lambda: seed(ctx))
        task = asyncio.create_task(host.run(assembly.activate, ExecutionRequest("cancel")))
        await entered.wait()
        await host.stop()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert events[-3:] == ["tool.cancelled", "tool.closed", "model.closed"]
        assert clients[0].active_streams == 0
        with pytest.raises(RuntimeError, match="关闭"):
            await assembly.activate(ExecutionRequest("late"))
        saved = json.loads((tmp_path / "framework" / "ctx.json").read_text(encoding="utf-8"))
        states = {entry["location"].get("part", entry["id"]): entry["value"] for entry in saved["entries"]}
        assert states[str(RUN)]["status"] == "cancelled"
        assert states["tool_results"]["status"] == "cancelled"

        restarted, restored, restored_ctx, _, restored_clients, _, _, _ = setup(tmp_path, behavior="quiet")
        await restarted.start()
        assert restored_clients[0].requests == []
        await restarted.run(restored.activate, ExecutionRequest("next"))
        assert restored.defaults is not None
        messages = cast(dict, restored.defaults.context_state.get(restored_ctx, ExecutionRequest("next")))["messages"]
        observation = json.loads(next(message["content"] for message in messages if message["role"] == "tool"))
        assert observation["status"] == "cancelled"
        await restarted.stop()

    asyncio.run(scenario())


def test_partial_tool_creation_failure_closes_owned_resources(tmp_path):
    async def scenario():
        host, _, ctx, registry, clients, _, events, _ = setup(tmp_path)

        async def broken_factory(**kwargs):
            events.append("tool.failed")
            raise RuntimeError("工具创建失败")

        other_id = Id("dev.assembly:tools/broken")
        registry.register(
            RegistryEntry(
                other_id,
                "tool",
                ToolSpec(
                    COMPONENT,
                    {
                        "name": "broken",
                        "description": "失败夹具",
                        "parameters": {"type": "object"},
                    },
                    factory=broken_factory,
                ),
                "test",
                register_to=TOOLS,
            )
        )

        def configure():
            seed(ctx)
            value = settings()
            value["tools"].append({"tool": str(other_id), "instance_id": "broken", "config": {}})
            ctx.set(CONFIG, value)

        with pytest.raises(RuntimeError, match="创建失败"):
            await host.start(configure=configure)
        assert events == ["model.created", "tool.created", "tool.failed", "tool.closed", "model.closed"]
        assert clients[0].closed and host.state == "stopped"

    asyncio.run(scenario())


def test_failed_model_close_can_retry_without_reclosing_tools(tmp_path):
    async def scenario():
        host, assembly, ctx, _, clients, _, events, _ = setup(tmp_path, behavior="close_failure")
        await host.start(configure=lambda: seed(ctx))
        with pytest.raises(RuntimeError, match="模型关闭失败"):
            await host.stop()
        assert not clients[0].closed and assembly.client is clients[0]
        assert ctx.get(CONFIG) and host.state == "failed"
        await host.stop()
        assert clients[0].closed and events.count("tool.closed") == 1 and host.state == "stopped"

    asyncio.run(scenario())


def test_capability_rejection_closes_created_model_before_tools(tmp_path):
    async def scenario():
        host, _, ctx, _, clients, _, events, _ = setup(tmp_path, capabilities=ChatCapabilities(streaming=False))
        with pytest.raises(UnsupportedCapability):
            await host.start(configure=lambda: seed(ctx))
        assert events == ["model.created", "model.closed"] and clients[0].closed

    asyncio.run(scenario())


def test_restore_marks_abandoned_run_without_automatic_activation(tmp_path):
    async def scenario():
        host, _, ctx, _, _, _, _, _ = setup(tmp_path)

        def configure():
            seed(ctx, tools=False)

        await host.start(configure=configure)

        # 模拟进程遗留运行；下一次恢复须识别它没有对应任务。
        def leave_abandoned_state():
            ctx.set(
                RUN,
                {"status": "running", "run_id": "abandoned", "execution_id": "old"},
                location={"instance_id": "main"},
            )
            ctx.set(
                WORK,
                {"status": "running", "text": "部分输出"},
                location={"instance_id": "main", "part": "model_output", "run_id": "abandoned"},
            )
            ctx.set(WORK, {"keep": True}, location={"instance_id": "other", "part": "owned"})

        leave_abandoned_state()
        await host.stop()
        restored, _, other_ctx, _, clients, _, _, _ = setup(tmp_path)
        await restored.start()
        state = other_ctx.get(RUN, location={"instance_id": "main"})
        assert isinstance(state, dict)
        assert state["status"] == "failed" and state["error"] == "InterruptedRun"
        assert clients[0].requests == []
        assert other_ctx.get(WORK, location={"instance_id": "other", "part": "owned"}) == {"keep": True}
        await restored.stop()

    asyncio.run(scenario())


def test_registered_assembly_runs_through_cli_host_without_bot_cli_dependency(tmp_path):
    async def scenario():
        host, _, ctx, registry, clients, _, _, _ = setup(tmp_path)
        await host.start(configure=lambda: seed(ctx))
        await host.stop()
        providers = Plugin(
            "testfactories", tuple(entry for entry in registry.entries() if entry.id.namespace == "dev.assembly")
        )
        output = StringIO()
        status = await run_cli(
            ["--data-dir", str(tmp_path), "--assembly", str(ASSEMBLY), "ctx", "get", str(CONFIG)],
            plugins=(
                adapter_plugin(),
                model_plugin(),
                react_plugin(),
                tools_plugin(),
                defaults_plugin(),
                assembly_plugin(),
                providers,
            ),
            output=output,
        )
        assert status == 0 and json.loads(output.getvalue())["instance_id"] == "main"
        assert len(clients) == 2 and all(client.closed and not client.requests for client in clients)

    asyncio.run(scenario())


def gate_model(client, monkeypatch, *, cleanup=None):
    entered, release = asyncio.Event(), asyncio.Event()
    original = client._chunks
    first = True

    async def chunks(request):
        nonlocal first
        if first:
            first = False
            entered.set()
            try:
                await release.wait()
            finally:
                if cleanup is not None:
                    cleanup[0].set()
                    await cleanup[1].wait()
        async for chunk in original(request):
            yield chunk

    monkeypatch.setattr(client, "_chunks", chunks)
    return entered, release


def test_runtime_submission_receipts_sequences_and_repeated_activation(tmp_path):
    async def scenario():
        host, assembly, ctx, _, clients, _, _, _ = setup(tmp_path)
        with pytest.raises(RuntimeError):
            assembly.runtime.submit("尚未启动")
        await host.start(configure=lambda: seed(ctx, tools=False))
        try:
            assert clients[0].requests == [] and assembly.runtime.current is None
            payload: dict[str, JsonValue] = {"text": "第一条"}
            first = assembly.runtime.submit(payload, sequence=3)
            payload["text"] = "外部修改"
            second = assembly.runtime.submit("第二条")
            assert first.sequence == 3 and second.sequence == 4
            assert first.guidance_id != second.guidance_id
            assert first.run is second.run is assembly.runtime.activate()
            before = ctx.snapshot()
            for sequence in (0, 3, 4, True):
                with pytest.raises(ValueError, match="序号"):
                    assembly.runtime.submit("重复", sequence=sequence)
            with pytest.raises(ValueError):
                assembly.runtime.submit(float("nan"))
            assert ctx.snapshot() == before
            result = await first.run.wait()
            assert result.status == "completed" and result.run_id == first.run.run_id
            assert assembly.agent is not None and assembly.defaults is not None
            messages = cast(dict, assembly.defaults.context_state.get(ctx, ExecutionRequest("read")))["messages"]
            assert json.loads(messages[0]["content"]) == {"text": "第一条"}
            assert messages[1]["content"] == "第二条" and len(clients[0].requests) == 1
            assert await assembly.runtime.cancel(first.run.run_id) is False
            third = assembly.runtime.submit("下一次")
            assert third.sequence == 5 and third.run.run_id != first.run.run_id
            assert (await third.run.wait()).status == "completed"
            with pytest.raises(ValueError):
                assembly.runtime.submit("已消费", sequence=5)
        finally:
            await host.stop()
        with pytest.raises(RuntimeError, match="关闭"):
            assembly.runtime.activate()

    asyncio.run(scenario())


def test_runtime_live_guidance_and_cancelled_waiter_keep_current_run(tmp_path, monkeypatch):
    async def scenario():
        host, assembly, ctx, _, clients, _, _, _ = setup(tmp_path)
        await host.start(configure=lambda: seed(ctx, tools=False))
        entered, release = gate_model(clients[0], monkeypatch)
        try:
            first = assembly.runtime.submit("先做这件事")
            await entered.wait()
            waiter = asyncio.create_task(first.run.wait())
            await asyncio.sleep(0)
            waiter.cancel()
            with pytest.raises(asyncio.CancelledError):
                await waiter
            second = assembly.runtime.submit("补充信息")
            assert second.run is first.run and not first.run.done
            release.set()
            assert (await second.run.wait()).status == "completed"
            assert len(clients[0].requests) == 2
            assert clients[0].requests[-1]["messages"][-1]["content"] == "补充信息"
            assert assembly.agent is not None
            assert assembly.agent.progress.get(ctx, ExecutionRequest("read")) == 2
        finally:
            release.set()
            await host.stop()

    asyncio.run(scenario())


@pytest.mark.parametrize("boundary", ["finish", "completed"])
def test_runtime_submission_at_finish_boundary_gets_followup_run(tmp_path, boundary):
    async def scenario():
        host, assembly, ctx, _, clients, _, _, _ = setup(tmp_path)
        await host.start(configure=lambda: seed(ctx, tools=False))
        followups, terminals = [], []

        def observe(change):
            state = change.value
            if change.address.key != RUN or not isinstance(state, dict):
                return
            if state["status"] in ("completed", "cancelled", "failed"):
                terminals.append((state["run_id"], state["status"]))
            match = state["status"] == "completed" if boundary == "completed" else state["phase"] == "finish"
            if match and not followups:
                followups.append(assembly.runtime.submit("收尾期间的输入"))

        subscription = ctx.subscribe(observe, key=RUN)
        try:
            first = assembly.runtime.submit("首次输入")
            assert (await first.run.wait()).status == "completed"
            assert len(followups) == 1 and followups[0].run.run_id != first.run.run_id
            assert (await followups[0].run.wait()).status == "completed"
            assert terminals == [(first.run.run_id, "completed"), (followups[0].run.run_id, "completed")]
            assert len(clients[0].requests) == 2
        finally:
            ctx.unsubscribe(subscription)
            await host.stop()

    asyncio.run(scenario())


def test_runtime_cancel_waits_for_cleanup_and_repeated_cancel_does_not_interrupt_it(tmp_path, monkeypatch):
    async def scenario():
        host, assembly, ctx, _, clients, _, _, _ = setup(tmp_path)
        await host.start(configure=lambda: seed(ctx, tools=False))
        cleaning, released = asyncio.Event(), asyncio.Event()
        entered, _ = gate_model(clients[0], monkeypatch, cleanup=(cleaning, released))
        try:
            submission = assembly.runtime.submit("阻塞调用")
            await entered.wait()
            extra = assembly.runtime.submit("取消时仍未消费的输入")
            first = asyncio.create_task(assembly.runtime.cancel(submission.run.run_id))
            await cleaning.wait()
            assert not first.done() and not submission.run.done
            with pytest.raises(AgentBusyError, match="取消"):
                assembly.runtime.submit("等待清理")
            second = asyncio.create_task(assembly.runtime.cancel(submission.run.run_id))
            await asyncio.sleep(0)
            first.cancel()
            with pytest.raises(asyncio.CancelledError):
                await first
            assert not second.done()
            released.set()
            assert await second is True
            assert (await submission.run.wait()).status == "cancelled"
            assert clients[0].active_streams == 0
            assert assembly.agent is not None
            assert [item["sequence"] for item in assembly.agent.pending(ExecutionRequest("read"))] == [extra.sequence]
            assert assembly.runtime.current is None
            resumed = assembly.runtime.activate()
            assert resumed.run_id != submission.run.run_id
            assert (await resumed.wait()).status == "completed"
            assert await assembly.runtime.cancel(submission.run.run_id) is False
        finally:
            released.set()
            await host.stop()

    asyncio.run(scenario())


def test_runtime_cancel_before_task_start_preserves_input_for_explicit_activation(tmp_path):
    async def scenario():
        host, assembly, ctx, _, clients, _, _, _ = setup(tmp_path)
        await host.start(configure=lambda: seed(ctx, tools=False))
        try:
            submission = assembly.runtime.submit("等待显式恢复")
            assert await assembly.runtime.cancel(submission.run.run_id) is True
            assert (await submission.run.wait()).status == "cancelled"
            assert clients[0].requests == []
            assert assembly.runtime.current is None
            assert (await assembly.runtime.activate().wait()).status == "completed"
            assert len(clients[0].requests) == 1
        finally:
            await host.stop()

    asyncio.run(scenario())


def test_runtime_failure_retains_new_input_without_automatic_retry(tmp_path, monkeypatch):
    async def scenario():
        host, assembly, ctx, _, clients, _, _, _ = setup(tmp_path)
        await host.start(configure=lambda: seed(ctx, tools=False))
        entered, release = gate_model(clients[0], monkeypatch)

        def fail(request):
            raise ValueError("故障夹具")

        clients[0].respond = fail
        try:
            first = assembly.runtime.submit("失败输入")
            await entered.wait()
            second = assembly.runtime.submit("稍后处理")
            release.set()
            result = await first.run.wait()
            assert result.status == "failed" and result.error == "ValueError"
            assert first.run is second.run and assembly.runtime.current is None
            assert len(clients[0].requests) == 1
            clients[0].respond = lambda request: FakeReply(("已恢复",))
            assert (await assembly.runtime.activate().wait()).status == "completed"
            assert clients[0].requests[-1]["messages"][-1]["content"] == "稍后处理"
        finally:
            release.set()
            await host.stop()

    asyncio.run(scenario())


def test_runtime_host_shutdown_cancels_tool_then_closes_resources_and_restores_pending(tmp_path):
    async def scenario():
        host, assembly, ctx, _, clients, _, events, entered = setup(tmp_path, behavior="wait")
        await host.start(configure=lambda: seed(ctx))
        first = assembly.runtime.submit("调用工具")
        await entered.wait()
        queued = assembly.runtime.submit("重启后处理")
        await host.stop()
        assert (await first.run.wait()).status == "cancelled"
        assert events[-3:] == ["tool.cancelled", "tool.closed", "model.closed"]
        assert clients[0].closed
        restored, other, other_ctx, _, new_clients, _, _, _ = setup(tmp_path, behavior="quiet")
        await restored.start()
        try:
            assert new_clients[0].requests == [] and other.runtime.current is None
            with pytest.raises(ValueError):
                other.runtime.submit("重放", sequence=queued.sequence)
            assert (await other.runtime.activate().wait()).status == "completed"
            assert other.agent is not None
            assert other.agent.progress.get(other_ctx, ExecutionRequest("read")) == queued.sequence
            messages = new_clients[0].requests[0]["messages"]
            observation = json.loads(next(message["content"] for message in messages if message["role"] == "tool"))
            assert observation["status"] == "cancelled"
        finally:
            await restored.stop()

    asyncio.run(scenario())


def test_runtime_prevents_mixing_manual_and_managed_owners(tmp_path, monkeypatch):
    async def scenario():
        host, assembly, ctx, _, clients, _, _, _ = setup(tmp_path)
        await host.start(configure=lambda: seed(ctx, tools=False))
        entered, release = gate_model(clients[0], monkeypatch)
        try:
            manual = asyncio.create_task(host.run(assembly.activate, ExecutionRequest("manual")))
            await entered.wait()
            with pytest.raises(AgentBusyError, match="混用"):
                assembly.runtime.submit("不能并行")
            release.set()
            await manual
            managed = assembly.runtime.submit("正式入口")
            with pytest.raises(AgentBusyError, match="混用"):
                await assembly.activate(ExecutionRequest("other"))
            assert (await managed.run.wait()).status == "completed"
        finally:
            release.set()
            await host.stop()

    asyncio.run(scenario())


@pytest.mark.parametrize("finish_error", [False, True])
def test_runtime_queued_cancellation_or_preceding_failure_keeps_input(tmp_path, finish_error):
    async def scenario():
        host, assembly, ctx, registry, clients, _, _, _ = setup(tmp_path)
        await host.start(configure=lambda: seed(ctx, tools=False))
        entered, release = asyncio.Event(), asyncio.Event()
        first_finish = True

        async def finish(request):
            nonlocal first_finish
            if first_finish:
                first_finish = False
                entered.set()
                await release.wait()
                if finish_error:
                    raise ValueError("收尾失败")

        identity = Id("dev.assembly:handlers/finish_gate")
        registry.register_many(component_entries(identity, finish, finish, provider="test"))
        assert assembly.agent is not None
        assembly.agent.slots["finish"].connect(ExecutionPlug(identity, finish))
        try:
            first = assembly.runtime.submit("第一条")
            await entered.wait()
            followup = assembly.runtime.submit("收尾后的输入")
            assert followup.run.run_id != first.run.run_id
            if not finish_error:
                assert await assembly.runtime.cancel(followup.run.run_id) is True
                assert not first.run.done
            release.set()
            result = await first.run.wait()
            next_result = await followup.run.wait()
            if finish_error:
                assert result.status == "failed" and next_result.error == "PreviousRunFailed"
            else:
                assert result.status == "completed" and next_result.status == "cancelled"
            assert len(clients[0].requests) == 1 and assembly.runtime.current is None
            assert assembly.agent.pending(ExecutionRequest("read"))[0]["sequence"] == followup.sequence
            assert (await assembly.runtime.activate().wait()).status == "completed"
            assert len(clients[0].requests) == 2
        finally:
            release.set()
            await host.stop()

    asyncio.run(scenario())


def test_runtime_late_cancel_does_not_change_completed_run(tmp_path):
    async def scenario():
        host, assembly, ctx, _, _, _, _, _ = setup(tmp_path)
        await host.start(configure=lambda: seed(ctx, tools=False))
        cancellations = []

        def observe(change):
            if isinstance(change.value, dict) and change.value.get("status") == "completed":
                cancellations.append(asyncio.create_task(assembly.runtime.cancel(change.value["run_id"])))

        subscription = ctx.subscribe(observe, key=RUN)
        try:
            run = assembly.runtime.submit("完成边界").run
            assert (await run.wait()).status == "completed"
            assert len(cancellations) == 1 and await cancellations[0] is False
            assert (await run.wait()).status == "completed"
        finally:
            ctx.unsubscribe(subscription)
            await host.stop()

    asyncio.run(scenario())


def test_runtime_rejects_reentrant_submission_without_losing_outer_input(tmp_path):
    async def scenario():
        host, assembly, ctx, _, clients, _, _, _ = setup(tmp_path)
        await host.start(configure=lambda: seed(ctx, tools=False))
        checked = []

        def observe(change):
            if not checked:
                checked.append(True)
                with pytest.raises(RuntimeError, match="重入"):
                    assembly.runtime.submit("重入")

        subscription = ctx.subscribe(observe, key=AGENTS, location={"instance_id": "main", "part": "inbox"})
        try:
            submitted = assembly.runtime.submit("外层输入")
            assert (await submitted.run.wait()).status == "completed"
            assert checked == [True]
            assert [m["content"] for m in clients[0].requests[0]["messages"] if m["role"] == "user"] == ["外层输入"]
        finally:
            ctx.unsubscribe(subscription)
            await host.stop()

    asyncio.run(scenario())


def test_runtime_cancelled_close_waiter_keeps_resource_cleanup_alive(tmp_path, monkeypatch):
    async def scenario():
        host, assembly, ctx, _, clients, _, events, _ = setup(tmp_path)
        await host.start(configure=lambda: seed(ctx, tools=False))
        cleaning, release = asyncio.Event(), asyncio.Event()
        entered, _ = gate_model(clients[0], monkeypatch, cleanup=(cleaning, release))
        run = assembly.runtime.submit("等待取消").run
        await entered.wait()
        closing = asyncio.create_task(assembly.runtime.close())
        await cleaning.wait()
        closing.cancel()
        with pytest.raises(asyncio.CancelledError):
            await closing
        assert not run.done and not clients[0].closed
        release.set()
        await assembly.runtime.close()
        assert (await run.wait()).status == "cancelled"
        await host.stop()
        assert events[-1] == "model.closed" and clients[0].closed

    asyncio.run(scenario())


def test_public_run_operations_bind_to_started_bot_and_unbind_on_stop(tmp_path, monkeypatch):
    async def scenario():
        host, assembly, ctx, registry, clients, _, _, _ = setup(tmp_path)
        for identity in (RUN_SUBMIT, RUN_ACTIVATE, RUN_CANCEL):
            entry = registry.get(identity)
            assert entry.kind == "operation" and callable(entry.target)
            assert entry.register_to == Id("org.aurora.core:registries/operations")
        with pytest.raises(LookupError, match="未绑定"):
            await invoke_operation(registry, RUN_SUBMIT, "尚未启动", instance_id="main")
        assert clients == []
        await host.start(configure=lambda: seed(ctx, tools=False))
        entered, release = gate_model(clients[0], monkeypatch)
        try:
            with pytest.raises(TypeError):
                await invoke_operation(registry, RUN_ACTIVATE)
            with pytest.raises(LookupError, match="未绑定"):
                await invoke_operation(registry, RUN_ACTIVATE, instance_id="missing")
            receipt = await invoke_operation(registry, RUN_SUBMIT, "公共入口", instance_id="main", sequence=1)
            assert isinstance(receipt, Submission)
            assert receipt.run is await invoke_operation(registry, RUN_ACTIVATE, instance_id="main")
            with pytest.raises(ValueError, match="序号"):
                await invoke_operation(registry, RUN_SUBMIT, "重复", instance_id="main", sequence=1)
            await entered.wait()
            assert await invoke_operation(registry, RUN_CANCEL, "unknown", instance_id="main") is False
            assert not receipt.run.done
            assert await invoke_operation(registry, RUN_CANCEL, receipt.run.run_id, instance_id="main") is True
            assert (await receipt.run.wait()).status == "cancelled"
            release.set()
            run = await invoke_operation(registry, RUN_ACTIVATE, instance_id="main")
            assert isinstance(run, RunHandle) and (await run.wait()).status == "completed"
            assembly.stop_accepting()
            with pytest.raises(RuntimeError, match="关闭"):
                await invoke_operation(registry, RUN_SUBMIT, "关闭后拒绝", instance_id="main")
        finally:
            release.set()
            await host.stop()
        with pytest.raises(LookupError, match="未绑定"):
            await invoke_operation(registry, RUN_CANCEL, "unknown", instance_id="main")

    asyncio.run(scenario())


@pytest.mark.parametrize("other_identity", ["main", "other"])
def test_public_run_operations_route_instances_without_overwriting_owner(tmp_path, monkeypatch, other_identity):
    async def scenario():
        first, a, ctx_a, registry, clients_a, _, _, _ = setup(tmp_path / "a")
        second, b, ctx_b, other_registry, clients_b, _, _, _ = setup(tmp_path / "b")
        # 显式共享分发服务，验证多个装配的选择和重复身份的启动清理。
        for identity in (RUN_CONTROL, RUN_SUBMIT, RUN_ACTIVATE, RUN_CANCEL):
            other_registry.replace(registry.get(identity))

        def configure_b():
            seed(ctx_b, tools=False)
            config = cast(dict, ctx_b.get(CONFIG))
            ctx_b.set(CONFIG, {**config, "instance_id": other_identity})

        await first.start(configure=lambda: seed(ctx_a, tools=False))
        try:
            if other_identity == "main":
                with pytest.raises(ValueError, match="已经绑定"):
                    await second.start(configure=configure_b)
                assert clients_b[0].closed and not clients_a[0].closed
                run = await invoke_operation(registry, RUN_ACTIVATE, instance_id="main")
                assert isinstance(run, RunHandle) and (await run.wait()).status == "completed"
                return
            await second.start(configure=configure_b)
            entered_a, release_a = gate_model(clients_a[0], monkeypatch)
            entered_b, release_b = gate_model(clients_b[0], monkeypatch)
            try:
                run_a = await invoke_operation(registry, RUN_ACTIVATE, instance_id="main")
                run_b = await invoke_operation(registry, RUN_ACTIVATE, instance_id="other")
                assert isinstance(run_a, RunHandle) and isinstance(run_b, RunHandle)
                assert a.runtime.current is run_a and b.runtime.current is run_b
                await entered_a.wait()
                await entered_b.wait()
                assert await invoke_operation(registry, RUN_CANCEL, run_a.run_id, instance_id="other") is False
                assert not run_a.done and not run_b.done
                assert await invoke_operation(registry, RUN_CANCEL, run_b.run_id, instance_id="other") is True
                assert (await run_b.wait()).status == "cancelled" and not run_a.done
                release_a.set()
                assert (await run_a.wait()).status == "completed"
                await first.stop()
                with pytest.raises(LookupError):
                    await invoke_operation(other_registry, RUN_ACTIVATE, instance_id="main")
                next_run = await invoke_operation(other_registry, RUN_ACTIVATE, instance_id="other")
                assert isinstance(next_run, RunHandle) and (await next_run.wait()).status == "completed"
            finally:
                release_a.set()
                release_b.set()
                await second.stop()
        finally:
            await first.stop()

    asyncio.run(scenario())


def test_run_operations_are_visible_in_cli_without_starting_assembly(tmp_path, monkeypatch):
    monkeypatch.setenv("COLUMNS", "200")
    output = StringIO()
    data = tmp_path / "unused"
    result = asyncio.run(
        run_cli(
            ["--data-dir", str(data), "id", "list"],
            plugins=(
                adapter_plugin(),
                model_plugin(),
                react_plugin(),
                tools_plugin(),
                defaults_plugin(),
                assembly_plugin(),
            ),
            output=output,
        )
    )
    assert result == 0
    for identity in (RUN_SUBMIT, RUN_ACTIVATE, RUN_CANCEL):
        assert str(identity) in output.getvalue()
    assert not data.exists()


async def cli_setup(root, *, behavior="normal"):
    """为真实 CLI 宿主准备可恢复配置与离线工厂。"""
    host, _, ctx, registry, clients, _, events, entered = setup(root, behavior=behavior)

    def configure():
        seed(ctx)
        if behavior == "tool_timeout":
            ctx.set(CONFIG, {**settings(), "tool_timeout": 0.01})

    await host.start(configure=configure)
    await host.stop()
    clients.clear()
    events.clear()
    plugins = (
        adapter_plugin(),
        model_plugin(),
        react_plugin(),
        tools_plugin(),
        defaults_plugin(),
        assembly_plugin(),
        Plugin("cli_fixture", tuple(entry for entry in registry.entries() if entry.provider == "test")),
    )
    argv = ["--data-dir", str(root), "--assembly", str(ASSEMBLY), "--namespace", "org.aurora.bot"]
    return plugins, argv, clients, events, entered


def test_bot_cli_submit_tool_loop_and_activate_restore(tmp_path):
    async def scenario():
        plugins, argv, clients, events, _ = await cli_setup(tmp_path)
        output = StringIO()
        assert (
            await run_cli([*argv, "run", "submit", "你好", "--instance-id", "main"], plugins=plugins, output=output)
            == 0
        )
        records = [json.loads(line) for line in output.getvalue().splitlines()]
        receipt, result = records[0], records[-1]
        assert receipt["event"] == "accepted" and receipt["sequence"] == 1 and receipt["guidance_id"]
        assert result["event"] == "result" and result["status"] == "completed"
        assert {record["run_id"] for record in records} == {receipt["run_id"]}
        assert {record["instance_id"] for record in records} == {"main"}
        model = [record for record in records if record["event"] == "model"]
        assert "".join(record["delta"] for record in model) == "first"
        assert len({record["execution_id"] for record in model}) == 2
        assert any(record["tool_calls"] for record in model)
        assert any(message["role"] == "tool" for message in clients[0].requests[-1]["messages"])
        assert clients[0].closed and events[-2:] == ["tool.closed", "model.closed"]
        output = StringIO()
        assert await run_cli([*argv, "run", "activate", "--instance-id", "main"], plugins=plugins, output=output) == 0
        restored = [json.loads(line) for line in output.getvalue().splitlines()]
        assert restored[0]["run_id"] != receipt["run_id"] and "sequence" not in restored[0]
        assert restored[-1]["status"] == "completed" and clients[1].closed
        assert any(message["role"] == "tool" for message in clients[1].requests[0]["messages"])

    asyncio.run(scenario())


@pytest.mark.parametrize("failure", [False, True])
def test_bot_cli_streams_before_completion_and_reports_failure(tmp_path, monkeypatch, failure):
    from aurora_adapter.model import ModelError

    async def scenario():
        plugins, argv, clients, _, _ = await cli_setup(tmp_path)
        emitted, release = asyncio.Event(), asyncio.Event()

        class Output(StringIO):
            def write(self, text):
                count = super().write(text)
                if text.startswith("{") and json.loads(text).get("delta") == "前":
                    emitted.set()
                return count

        async def chunks(self, request):
            yield {"type": "text", "text": "前"}
            await release.wait()
            if failure:
                raise ModelError("测试失败")
            yield {"type": "text", "text": "后"}
            yield {"type": "finish", "reason": "stop"}

        monkeypatch.setattr(FakeModel, "_chunks", chunks)
        output = Output()
        task = asyncio.create_task(
            run_cli([*argv, "run", "submit", "测试", "--instance-id", "main"], plugins=plugins, output=output)
        )
        try:
            await asyncio.wait_for(emitted.wait(), timeout=5)
            assert not task.done() and clients[0].active_streams == 1
            release.set()
            assert await task == (1 if failure else 0)
            records = [json.loads(line) for line in output.getvalue().splitlines()]
            assert "".join(record["delta"] for record in records if record["event"] == "model") == (
                "前" if failure else "前后"
            )
            assert records[-1]["status"] == ("failed" if failure else "completed")
            assert records[-1]["error"] == ("ModelError" if failure else None)
            assert clients[0].closed and clients[0].active_streams == 0
        finally:
            release.set()
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(scenario())


def test_bot_cli_cancel_command_targets_current_host_run(tmp_path):
    from aurora_cli.declarations import command_plugin, read_command
    from aurora_cli.execution import execute_command

    async def scenario():
        plugins, argv, clients, events, entered = await cli_setup(tmp_path, behavior="wait")

        async def execute(context):
            submit = read_command(context.registry.get(Id("org.aurora.bot:commands/run/submit")))
            cancel = read_command(context.registry.get(Id("org.aurora.bot:commands/run/cancel")))
            task = asyncio.create_task(execute_command(submit, context, {"payload": "等待", "instance_id": "main"}))
            try:
                await asyncio.wait_for(entered.wait(), timeout=5)
                receipt = json.loads(context.output.getvalue().splitlines()[0])
                await execute_command(cancel, context, {"run_id": "unknown", "instance_id": "main"})
                assert not task.done()
                await execute_command(cancel, context, {"run_id": receipt["run_id"], "instance_id": "main"})
                assert await task == 130
            finally:
                if not task.done():
                    task.cancel()
                await asyncio.gather(task, return_exceptions=True)

        extension = command_plugin(
            "cli_cancel", {"cancel_test": {"help": "同宿主取消", "runtime": True, "executor": execute}}
        )
        output = StringIO()
        assert (
            await run_cli([*argv, "org.aurora.cli:commands/cancel_test"], plugins=(*plugins, extension), output=output)
            == 0
        )
        records = [json.loads(line) for line in output.getvalue().splitlines()]
        cancelled = [record["cancelled"] for record in records if record["event"] == "cancel"]
        assert cancelled == [False, True]
        assert [record["status"] for record in records if record["event"] == "result"] == ["cancelled"]
        assert events[-3:] == ["tool.cancelled", "tool.closed", "model.closed"] and clients[0].closed

    asyncio.run(scenario())


def test_bot_cli_interrupt_cancels_tool_and_persists_terminal(tmp_path):
    async def scenario():
        plugins, argv, clients, events, entered = await cli_setup(tmp_path, behavior="wait")
        output = StringIO()
        task = asyncio.create_task(
            run_cli([*argv, "run", "submit", "等待", "--instance-id", "main"], plugins=plugins, output=output)
        )
        try:
            await asyncio.wait_for(entered.wait(), timeout=5)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            records = [json.loads(line) for line in output.getvalue().splitlines()]
            assert records[-1]["event"] == "result" and records[-1]["status"] == "cancelled"
            assert events[-3:] == ["tool.cancelled", "tool.closed", "model.closed"]
            assert clients[0].closed
            restored, assembly, ctx, _, _, _, _, _ = setup(tmp_path)
            await restored.start()
            try:
                assert assembly.agent is not None
                state = cast(dict, ctx.get(RUN, location={"instance_id": "main"}))
                assert state["status"] == "cancelled" and state["run_id"] == records[-1]["run_id"]
            finally:
                await restored.stop()
            resumed_output = StringIO()
            assert (
                await run_cli(
                    [*argv, "run", "activate", "--instance-id", "main"], plugins=plugins, output=resumed_output
                )
                == 0
            )
            resumed = [json.loads(line) for line in resumed_output.getvalue().splitlines()]
            assert resumed[-1]["status"] == "completed" and resumed[-1]["run_id"] != records[-1]["run_id"]
            assert events.count("tool.executed") == 1
            messages = clients[1].requests[0]["messages"]
            observations = [json.loads(message["content"]) for message in messages if message["role"] == "tool"]
            assert len(observations) == 1 and observations[0]["status"] == "cancelled"
        finally:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(scenario())


def test_bot_cli_output_failure_releases_subscription_and_run(tmp_path):
    from aurora_bot.cli import submit
    from aurora_cli.declarations import CommandContext
    from aurora_core import entry_from

    async def scenario():
        host, assembly, ctx, registry, clients, _, _, _ = setup(tmp_path)
        subscriptions = []
        subscribe = ctx.subscribe

        def tracked(callback, **filters):
            handle = subscribe(callback, **filters)
            subscriptions.append(handle)
            return handle

        registry.register(entry_from(ctx.subscribe, provider="test"))
        registry.replace(RegistryEntry(Id("org.aurora.core:operations/ctx/subscribe"), "operation", tracked, "test"))
        registry.register(entry_from(ctx.unsubscribe, provider="test"))

        class BrokenOutput(StringIO):
            def write(self, text):
                raise BrokenPipeError("输出已关闭")

        await host.start(configure=lambda: seed(ctx))
        try:
            with pytest.raises(BrokenPipeError):
                await submit(CommandContext(tmp_path, BrokenOutput(), registry, ()), "测试", instance_id="main")
            assert assembly.runtime.current is None
            assert len(subscriptions) == 1 and not ctx.unsubscribe(subscriptions[0])
            assert clients[0].active_streams == 0
        finally:
            await host.stop()

    asyncio.run(scenario())


def test_bot_cli_sigint_returns_130_after_stream_cleanup(tmp_path):
    import os
    import subprocess
    import sys
    from pathlib import Path

    launcher = """
import asyncio
import importlib
import json
import runpy
import signal
import sys
from pathlib import Path
from aurora_adapter.model.testing import FakeModel

source = runpy.run_path(sys.argv[1])
entry = importlib.import_module("aurora_cli.main")

class Output:
    def write(self, text):
        sys.stdout.write(text)
        if text.startswith("{") and json.loads(text).get("delta") == "部分输出":
            asyncio.get_running_loop().call_soon(signal.raise_signal, signal.SIGINT)
        return len(text)
    def flush(self):
        sys.stdout.flush()

async def chunks(self, request):
    yield {"type": "text", "text": "部分输出"}
    await asyncio.Event().wait()

async def run():
    plugins, argv, clients, events, _ = await source["cli_setup"](Path(sys.argv[2]))
    FakeModel._chunks = chunks
    try:
        return await source["run_cli"](
            [*argv, "run", "submit", "测试中断", "--instance-id", "main"], plugins=plugins, output=Output()
        )
    finally:
        assert clients[0].active_streams == 0 and clients[0].closed
        assert events[-2:] == ["tool.closed", "model.closed"]

entry.run_cli = run
raise SystemExit(entry.main())
"""
    result = subprocess.run(
        [sys.executable, "-c", launcher, str(Path(__file__).resolve()), str(tmp_path)],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        timeout=15,
    )
    assert result.returncode == 130, result.stderr
    records = [json.loads(line) for line in result.stdout.splitlines()]
    assert records[-1]["status"] == "cancelled" and records[-1]["event"] == "result"
    assert any(record.get("delta") == "部分输出" for record in records)
    snapshot = json.loads((tmp_path / "framework" / "ctx.json").read_text(encoding="utf-8"))
    run = next(entry["value"] for entry in snapshot["entries"] if entry["id"] == str(RUN))
    assert run["status"] == "cancelled" and run["run_id"] == records[-1]["run_id"]


@pytest.mark.parametrize("behavior,code", [("tool_failure", "tool_failed"), ("tool_timeout", "timeout")])
def test_bot_cli_tool_errors_are_observed_and_survive_restart(tmp_path, behavior, code):
    async def scenario():
        plugins, argv, clients, events, _ = await cli_setup(tmp_path, behavior=behavior)
        output = StringIO()
        assert (
            await run_cli([*argv, "run", "submit", "执行工具", "--instance-id", "main"], plugins=plugins, output=output)
            == 0
        )
        records = [json.loads(line) for line in output.getvalue().splitlines()]
        terminal = [
            record["state"] for record in records if record["event"] == "run" and record["state"]["status"] != "running"
        ]
        assert len(terminal) == 1 and terminal[0]["status"] == records[-1]["status"] == "completed"
        assert len(clients[0].requests) == 2
        messages = clients[0].requests[-1]["messages"]
        observation = json.loads(next(message["content"] for message in messages if message["role"] == "tool"))
        assert observation["status"] == "failed" and observation["error"]["code"] == code
        assert events[-2:] == ["tool.closed", "model.closed"] and clients[0].closed
        if behavior == "tool_timeout":
            assert events.index("tool.cancelled") < events.index("tool.closed")
        restored_output = StringIO()
        assert (
            await run_cli([*argv, "run", "activate", "--instance-id", "main"], plugins=plugins, output=restored_output)
            == 0
        )
        restored_messages = clients[1].requests[0]["messages"]
        assert restored_messages[: len(messages)] == messages
        assert events.count("tool.executed") == 1
        assert json.loads(restored_output.getvalue().splitlines()[-1])["status"] == "completed"

    asyncio.run(scenario())


def test_conversation_http_receipts_validation_disconnect_and_restart(tmp_path):
    async def scenario():
        host, assembly, ctx, registry, _, _, events, entered = setup(tmp_path, behavior="wait")
        await host.start(configure=lambda: seed(ctx))
        contract = describe_contract(extensions=[describe_conversation()])
        Draft202012Validator.check_schema(contract)

        def validate(name, body):
            Draft202012Validator({"$defs": contract["$defs"], "$ref": f"#/$defs/{name}"}).validate(body)

        async with ClientSession() as session:
            try:
                async with (
                    serve(registry, keys=[], port=0) as url,
                    session.post(url + "/conversation/info", json={}) as response,
                ):
                    assert response.status == 404
                async with serve(registry, keys=[], endpoints=[CONVERSATION], port=0) as url:

                    async def call(action, payload, expected=200):
                        binding = contract["http"][f"conversation{action}"]
                        async with session.post(url + binding["path"], json=payload) as response:
                            assert response.status == expected, await response.text()
                            body = await response.json()
                        validate(f"Conversation{action}Response" if expected == 200 else "ErrorResponse", body)
                        return body.get("result", body.get("error"))

                    info = await call("Info", {})
                    assert info["instance_ids"] == ["main"]
                    scope = {"session_id": info["session_id"], "instance_id": "main"}
                    message = {**scope, "request_id": "one", "text": "开始"}
                    for invalid in (
                        {},
                        {**message, "text": " "},
                        {**message, "extra": 1},
                        {**message, "request_id": 7},
                    ):
                        await call("Submit", invalid, 400)
                    assert await call("Submit", {**message, "instance_id": "absent"}, 404)
                    first, duplicate = await asyncio.gather(call("Submit", message), call("Submit", message))
                    assert first == duplicate and first["accepted"] is True
                    await asyncio.wait_for(entered.wait(), 2)
                    conflict = await call("Submit", {**message, "text": "不同内容"}, 409)
                    assert conflict["code"] == "request_conflict"
                    second = await call("Submit", {**message, "request_id": "two", "text": "运行中引导"})
                    assert first["run_id"] == second["run_id"] and first["guidance_id"] != second["guidance_id"]
                    assert (await call("Query", {**scope, "request_id": "one"}))["run_status"] == "pending"
                    assert (await call("Cancel", {**scope, "run_id": "unknown"}))["cancelled"] is False
                    await call("Cancel", {**scope, "instance_id": "absent", "run_id": first["run_id"]}, 404)
                    async with session.post(
                        url + "/conversation/submit", json=message, headers={"Origin": "http://localhost"}
                    ) as response:
                        assert response.status == 403
                # API 退出只停止观察，装配仍持有运行任务。
                assert assembly.runtime.current is not None and not assembly.runtime.current.done
                async with serve(registry, keys=[], endpoints=[CONVERSATION], port=0) as url:
                    assert await call("Submit", message) == first
                    assert (await call("Cancel", {**scope, "run_id": first["run_id"]}))["cancelled"] is True
                    assert "tool.cancelled" in events
                    assert (await call("Query", {**scope, "request_id": "one"}))["run_status"] == "cancelled"
                    assert (await call("Cancel", {**scope, "run_id": first["run_id"]}))["cancelled"] is False
            finally:
                await host.stop()
            restored, other, other_ctx, other_registry, clients, _, _, _ = setup(tmp_path)
            await restored.start()
            try:
                async with serve(other_registry, keys=[], endpoints=[CONVERSATION], port=0) as url:
                    new_info = await call("Info", {})
                    assert new_info["session_id"] != info["session_id"]
                    for action, data in (
                        ("Submit", message),
                        ("Query", {**scope, "request_id": "one"}),
                        ("Cancel", {**scope, "run_id": first["run_id"]}),
                    ):
                        assert (await call(action, data, 409))["code"] == "session_expired"
                    assert clients[0].requests == [] and other.runtime.current is None
                    assert (
                        await call("Query", {**scope, "session_id": new_info["session_id"], "request_id": "one"}, 404)
                    )["code"] == "not_found"
                    assert other_ctx.list(key=AGENTS)
            finally:
                await restored.stop()

    asyncio.run(scenario())


def test_typescript_direct_conversation_uses_real_bot_runtime(tmp_path):
    async def scenario():
        host, assembly, ctx, registry, _, _, events, _ = setup(tmp_path, behavior="wait")
        await host.start(configure=lambda: seed(ctx))
        process = None
        try:
            async with serve(registry, keys=[], endpoints=[CONVERSATION], port=0) as url:
                process = await asyncio.create_subprocess_exec(
                    "node",
                    str(Path(__file__).resolve().parents[1] / "fixtures/conversation_client_process.mjs"),
                    url,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                output, errors = await asyncio.wait_for(process.communicate(), 15)
                assert process.returncode == 0, errors.decode("utf-8")
                assert json.loads(output) == {"status": "cancelled"}
                assert assembly.runtime.current is None
                assert events.count("tool.executed") == 1 and "tool.cancelled" in events
        finally:
            if process is not None and process.returncode is None:
                process.kill()
                await process.communicate()
            await host.stop()

    asyncio.run(scenario())


@pytest.mark.parametrize("outcome", ["completed", "failed", "cancelled"])
def test_compaction_failure_preserves_execution_failure_and_releases_ownership(tmp_path, monkeypatch, outcome):
    async def scenario():
        host, assembly, ctx, *_ = setup(tmp_path)
        await host.start(configure=lambda: seed(ctx, tools=False))
        original = asyncio.CancelledError() if outcome == "cancelled" else ValueError("执行失败")
        cleanup = RuntimeError("清理失败")

        async def execute(request):
            if outcome != "completed":
                raise original

        def compact():
            raise cleanup

        with monkeypatch.context() as patch:
            patch.setattr(assembly.agent, "execute", execute)
            patch.setattr(assembly, "_compact", compact)
            expected = cleanup if outcome == "completed" else original
            with pytest.raises(type(expected)) as raised:
                await assembly.activate(ExecutionRequest("cleanup-test"))
            assert raised.value is expected
            if outcome != "completed":
                assert raised.value.__cause__ is cleanup
            assert not assembly._executing
        await host.stop()

    asyncio.run(scenario())

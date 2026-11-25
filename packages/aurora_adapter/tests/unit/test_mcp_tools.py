"""验证 MCP 工具发现、agent 执行契约和单次请求边界；不连接外部服务。"""

import asyncio
import copy
import re
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import cast

import httpx2
import pytest
from aurora_adapter.mcp import CONFIG_STATE, PROTOCOL_VERSION, MCPClientError, MCPClients
from aurora_adapter.mcp import transports as client_module
from aurora_adapter.mcp.catalog import automatic_name
from aurora_adapter.mcp.configuration import MCP_CONFIG
from aurora_adapter.mcp.tools import MCPTools
from aurora_agent.tools import TOOLS, ToolExecutor, ToolRejected, ToolSpec
from aurora_control import ExecutionPlug, ExecutionRequest, StateBinding, component_entries
from aurora_core import Id
from aurora_core.bootstrap import bootstrap
from aurora_core.ctx import Context, StateKey
from aurora_core.discovery import load_plugins, register_plugins
from aurora_core.hooks import HookConnections
from aurora_core.lifecycle import install_lifecycle_slots
from aurora_core.registry import RegistryEntry
from aurora_core.storage import StorageService
from mcp.shared.exceptions import MCPError
from mcp.types import (
    CONNECTION_CLOSED,
    HEADER_MISMATCH,
    REQUEST_TIMEOUT,
    CallToolResult,
    InputRequiredResult,
    ListToolsResult,
    ServerCapabilities,
    Tool,
    ToolsCapability,
)

STATE = Id("dev.mcp:state/work")
TOOL = Id("org.aurora.adapter:tools/mcp/local_echo")
PARAMETERS = {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}


def declaration(**changes):
    return {"include": ["remote.echo"], "aliases": {"remote.echo": "local_echo"}, **changes}


class Session:
    def __init__(self):
        self.calls, self.cursors = [], []
        self.pages = {None: ListToolsResult(tools=[Tool(name="remote.echo", input_schema=PARAMETERS)])}
        self.result = CallToolResult.model_validate(
            {"content": [{"type": "text", "text": "返回"}], "structuredContent": {"text": "返回"}}
        )
        self.error = None
        self.wait = False
        self.entered, self.finished = asyncio.Event(), asyncio.Event()

    async def list_tools(self, *, params):
        self.cursors.append(params.cursor)
        return self.pages[params.cursor]

    async def call_tool(self, name, arguments, *, allow_input_required):
        assert allow_input_required
        self.calls.append((name, arguments))
        self.entered.set()
        try:
            if self.wait:
                await asyncio.Event().wait()
            if self.error is not None:
                raise self.error
            return self.result
        finally:
            self.finished.set()


@pytest.fixture
def environment(tmp_path, monkeypatch):
    session, closed = Session(), []
    client = SimpleNamespace(
        session=session,
        protocol_version=PROTOCOL_VERSION,
        server_capabilities=ServerCapabilities(tools=ToolsCapability()),
    )

    @asynccontextmanager
    async def open_client(config, resolver, negotiation, *, workspace_root=None):
        try:
            yield client
        finally:
            closed.append(config["connection_id"])

    monkeypatch.setattr(client_module, "open_client", open_client)
    registry = bootstrap()
    install_lifecycle_slots(registry)
    register_plugins(
        registry,
        load_plugins(
            enabled=[
                "aurora_config",
                "aurora_adapter.mcp",
                "aurora_agent.tools",
                "aurora_adapter.mcp.tools",
            ]
        ),
    )
    registry.register(RegistryEntry(STATE, "state_key", StateKey(), "test"))
    ctx, hooks, storage = Context(registry), HookConnections(registry), StorageService(tmp_path)
    config = {
        "schema_version": 2,
        "servers": {
            "local": {
                "type": "remote",
                "protocol": PROTOCOL_VERSION,
                "url": "http://localhost/mcp",
                "tools": declaration(),
            }
        },
    }
    ctx.set(CONFIG_STATE, config)
    clients = MCPClients(ctx, hooks)
    bridge = MCPTools(registry, ctx, hooks, clients)

    @asynccontextmanager
    async def start(*, discover=True, timeout=1.0):
        clients.configure()
        await clients.prepare()
        try:
            if not discover:
                yield None
                return
            await bridge.prepare()

            def state(name):
                return StateBinding(STATE, (("part", name),))

            executor = ToolExecutor(
                ctx,
                registry,
                hooks,
                request_state=state("request"),
                output_state=state("result"),
                current_state=state("current"),
                timeout=timeout,
            )
            spec = cast(ToolSpec, registry.get(TOOL).target)
            assert spec.factory is not None
            instance = await spec.factory(
                ctx=ctx,
                storage=storage,
                instance_id="echo-instance",
                input_state=state("input"),
                output_state=state("output"),
                config={},
            )
            executor.connect(TOOL, instance.plug)
            yield executor, instance
            if instance.aclose:
                await instance.aclose()
        finally:
            await clients.clean()

    yield SimpleNamespace(**locals())
    hooks.close()
    ctx.close()
    storage.close()


async def submit(env, executor, arguments=None):
    request = ExecutionRequest("run")
    executor.request_state.set(
        env.ctx,
        request,
        {
            "turn_id": "turn",
            "calls": [
                {"id": "call", "name": "local_echo", "arguments": {"text": "输入"} if arguments is None else arguments},
            ],
        },
    )
    await executor.execute(request)
    return cast(dict, executor.output_state.get(env.ctx, request))["results"][0]


@pytest.mark.parametrize(
    "value",
    [
        declaration(aliases={"remote.echo": "bad-name"}),
        declaration(aliases={"remote.echo": "a__b"}),
        declaration(aliases={"remote.echo": "a" * 65}),
        declaration(aliases={"missing": "valid"}),
        declaration(include=[""]),
        declaration(include=["remote.echo", "remote.echo"]),
    ],
)
def test_invalid_selection_rejected_before_network(value):
    with pytest.raises(ValueError):
        MCP_CONFIG.parse(
            {
                "schema_version": 2,
                "servers": {"local": {"type": "remote", "url": "http://localhost/mcp", "tools": value}},
            }
        )


def test_discovery_is_explicit_paginated_and_names_stay_stable(environment):
    env = environment
    env.session.pages[None] = ListToolsResult(
        tools=[Tool(name="unused", input_schema={"type": "object"})], next_cursor="p2"
    )
    env.session.pages["p2"] = ListToolsResult(tools=[Tool(name="remote.echo", input_schema=PARAMETERS)])
    assert env.registry.view(register_to=TOOLS) == ()

    async def scenario():
        async with env.start() as (executor, instance):
            assert env.session.cursors == [None, "p2"]
            assert executor.definitions()[0]["name"] == "local_echo"
            assert instance.plug.instance_id == "echo-instance"
            result = await submit(env, executor)
            assert result["status"] == "completed" and result["call_id"] == "call"
            assert result["value"]["structuredContent"] == {"text": "返回"}
            assert env.session.calls == [("remote.echo", {"text": "输入"})]
            with pytest.raises(RuntimeError, match="重建宿主"):
                await env.bridge.prepare()
            assert len(env.registry.view(register_to=TOOLS)) == 1

    asyncio.run(scenario())


@pytest.mark.parametrize("mode", ["empty", "disabled"])
def test_v2_selection_does_not_expand_exposure(environment, mode):
    env = environment
    server = env.config["servers"]["local"]
    if mode == "empty":
        server["tools"] = {"include": []}
    elif mode == "disabled":
        server["enabled"] = False
    env.ctx.set(CONFIG_STATE, env.config)

    async def scenario():
        async with env.start(discover=False):
            await env.bridge.prepare()
            assert env.bridge.prepared
            assert env.session.cursors == []
            assert env.registry.view(register_to=TOOLS) == ()

    asyncio.run(scenario())


def test_catalog_has_its_own_total_budget(environment):
    env = environment
    finished = []

    async def list_tools(*, params):
        try:
            await asyncio.Event().wait()
        finally:
            finished.append(True)

    env.session.list_tools = list_tools
    env.config["servers"]["local"]["timeout"] = {"catalog": 0.02, "execution": 10}
    env.ctx.set(CONFIG_STATE, env.config)

    async def scenario():
        async with env.start(discover=False):
            with pytest.raises(TimeoutError):
                await env.bridge.prepare()
            assert finished == [True]
            assert env.registry.view(register_to=TOOLS) == ()
        assert env.closed == ["local"]

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "server,remote,expected",
    [
        ("Test.Name", "remote.echo", "mcp_test_name_remote_echo_102dcb67e2fd"),
        ("srv", "读取文件", "mcp_srv_x_f0679455c80a"),
        ("a", "Kİ", "mcp_a_x_e50fdc6d3c76"),
    ],
)
def test_automatic_name_preserves_v2_identity(server, remote, expected):
    assert automatic_name(server, remote) == expected


def test_automatic_names_disambiguate_slugs_and_truncation():
    pairs = [("A.B", "echo"), ("a-b", "echo"), ("A" * 80, "B" * 100), ("A" * 80, "B" * 101)]
    names = [automatic_name(*pair) for pair in pairs]
    assert len(set(names)) == len(pairs)
    assert all(len(name) <= 58 and re.fullmatch(r"[a-z][a-z0-9]*(?:_[a-z0-9]+)*", name) for name in names)


@pytest.mark.parametrize("reverse", [False, True])
def test_automatic_selection_is_stable_across_servers_and_directory_order(environment, reverse):
    env = environment
    env.config["servers"]["local"]["tools"] = {}
    env.config["servers"]["second"] = copy.deepcopy(env.config["servers"]["local"])
    tools = [Tool(name=name, input_schema=PARAMETERS) for name in ("remote.echo", "读取", "remote-echo")]
    env.session.pages[None] = ListToolsResult(tools=tools[::-1] if reverse else tools)
    if reverse:
        env.config["servers"] = dict(reversed(list(env.config["servers"].items())))
    env.ctx.set(CONFIG_STATE, env.config)

    async def scenario():
        with pytest.raises(RuntimeError, match="尚未完成"):
            _ = env.bridge.tool_ids
        async with env.start(discover=False):
            await env.bridge.prepare()
            assert env.bridge.tool_ids == tuple(
                Id(f"org.aurora.adapter:tools/mcp/{automatic_name(server, remote)}")
                for server in ("local", "second")
                for remote in sorted(tool.name for tool in tools)
            )
            assert len(set(env.bridge.tool_ids)) == 6
            assert env.session.cursors == [None, None]

    asyncio.run(scenario())


def test_wildcard_filters_and_alias_preserve_selected_identity(environment):
    env = environment
    env.config["servers"]["local"]["tools"] = {"exclude": ["hidden"], "aliases": {"remote.echo": "local_echo"}}
    env.session.pages[None] = ListToolsResult(
        tools=[
            Tool(name="hidden", input_schema={"type": "string"}),
            Tool(name="remote.echo", input_schema=PARAMETERS),
            Tool(name="extra", input_schema=PARAMETERS),
        ]
    )
    env.ctx.set(CONFIG_STATE, env.config)

    async def scenario():
        async with env.start() as (executor, _):
            assert len(env.bridge.tool_ids) == 2 and TOOL in env.bridge.tool_ids
            assert (await submit(env, executor))["status"] == "completed"
            assert env.session.calls == [("remote.echo", {"text": "输入"})]

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "selection", [{"include": ["missing"]}, {"exclude": ["missing"]}, {"aliases": {"missing": "missing_alias"}}]
)
def test_unknown_explicit_catalog_names_fail_atomically(environment, selection):
    env = environment
    env.config["servers"]["local"]["tools"] = selection
    env.ctx.set(CONFIG_STATE, env.config)

    async def scenario():
        async with env.start(discover=False):
            before = env.registry.entries()
            with pytest.raises(MCPClientError, match="selected_tool_missing"):
                await env.bridge.prepare()
            assert env.registry.entries() == before and not env.bridge.prepared

    asyncio.run(scenario())


@pytest.mark.parametrize("conflict", ["local", "alias", "digest"])
def test_automatic_and_explicit_names_share_one_conflict_check(environment, monkeypatch, conflict):
    env = environment
    env.config["servers"]["local"]["tools"] = {}
    name = automatic_name("local", "remote.echo")
    if conflict == "local":
        env.registry.register(
            RegistryEntry(
                Id("dev.mcp:tools/existing"),
                "tool",
                ToolSpec(
                    Id("dev.mcp:components/tool"), {"name": name, "description": "本地工具", "parameters": PARAMETERS}
                ),
                "test",
                register_to=TOOLS,
            )
        )
    else:
        env.session.pages[None].tools.append(Tool(name="extra", input_schema=PARAMETERS))
        if conflict == "alias":
            env.config["servers"]["local"]["tools"] = {"aliases": {"extra": name}}
        else:
            monkeypatch.setattr("aurora_adapter.mcp.catalog.automatic_name", lambda *args: name)
    env.ctx.set(CONFIG_STATE, env.config)

    async def scenario():
        async with env.start(discover=False):
            before = env.registry.entries()
            with pytest.raises(MCPClientError, match="tool_name_conflict"):
                await env.bridge.prepare()
            assert env.registry.entries() == before and not env.bridge.prepared

    asyncio.run(scenario())


def test_default_wildcard_leaves_resource_only_service_available(environment):
    env = environment
    env.client.server_capabilities = ServerCapabilities()
    env.config["servers"]["local"]["tools"] = {}
    env.ctx.set(CONFIG_STATE, env.config)

    async def scenario():
        async with env.start(discover=False):
            await env.bridge.prepare()
            assert env.bridge.tool_ids == () and env.session.cursors == []
            async with env.clients.connection("local") as client:
                assert client is env.client

    asyncio.run(scenario())


def test_discovery_uses_the_same_snapshot_as_client_creation(environment):
    env = environment

    async def scenario():
        async with env.start(discover=False):
            env.config["servers"]["local"]["tools"] = {"include": ["missing"]}
            env.ctx.set(CONFIG_STATE, env.config)
            exposed = env.clients.server_configurations()
            exposed["local"]["tools"]["include"].clear()
            await env.bridge.prepare()
            assert env.bridge.tool_ids == (TOOL,)

    asyncio.run(scenario())


@pytest.mark.parametrize("problem", ["missing", "duplicate", "cursor", "schema", "conflict", "capability"])
def test_discovery_failure_does_not_partially_register(environment, problem):
    env = environment
    env.config["servers"]["local"]["tools"]["include"].append("second")
    env.config["servers"]["local"]["tools"]["aliases"]["second"] = "second"
    tools = [Tool(name="remote.echo", input_schema=PARAMETERS), Tool(name="second", input_schema=PARAMETERS)]
    if problem == "missing":
        tools.pop()
    elif problem == "duplicate":
        tools.append(tools[0])
    elif problem == "schema":
        tools[1] = Tool(name="second", input_schema={"type": "string"})
    elif problem == "conflict":
        env.registry.register(RegistryEntry(Id("org.aurora.adapter:tools/mcp/second"), "test", None, "test"))
    elif problem == "capability":
        env.client.server_capabilities = ServerCapabilities()
    env.session.pages[None] = ListToolsResult(tools=tools, next_cursor="repeat" if problem == "cursor" else None)
    env.session.pages["repeat"] = ListToolsResult(tools=[], next_cursor="repeat")
    env.ctx.set(CONFIG_STATE, env.config)

    async def scenario():
        async with env.start(discover=False):
            before = env.registry.entries()
            with pytest.raises((MCPClientError, ValueError)):
                await env.bridge.prepare()
            assert env.registry.entries() == before
            assert not env.bridge.prepared

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "error,code",
    [
        (MCPError(-32602, "secret-server-message"), "mcp_protocol_error"),
        (MCPError(HEADER_MISMATCH, "secret-server-message"), "mcp_protocol_error"),
        (MCPError(CONNECTION_CLOSED, "secret-server-message"), "mcp_result_unknown"),
        (MCPError(REQUEST_TIMEOUT, "secret-server-message"), "mcp_timeout"),
        (httpx2.ReadError("secret-server-message"), "mcp_result_unknown"),
        (httpx2.ReadTimeout("secret-server-message"), "mcp_timeout"),
        (TimeoutError("secret-server-message"), "mcp_timeout"),
        (ValueError("secret-server-message"), "mcp_invalid_result"),
        (RuntimeError("secret-server-message"), "mcp_invalid_result"),
    ],
)
def test_safe_error_observations_never_retry(environment, error, code, caplog):
    env = environment
    env.session.error = error

    async def scenario():
        async with env.start() as (executor, _):
            result = await submit(env, executor)
            assert result["status"] == "failed" and result["error"]["code"] == code
            assert len(env.session.calls) == 1
            assert "secret-server-message" not in repr(env.ctx.snapshot()) + caplog.text

    asyncio.run(scenario())


@pytest.mark.parametrize("business_error", [False, True])
def test_content_blocks_and_structured_result_are_preserved(environment, business_error):
    env = environment
    env.session.result = CallToolResult.model_validate(
        {
            "content": [
                {"type": "text", "text": "说明"},
                {"type": "image", "data": "AA==", "mimeType": "image/png"},
                {"type": "resource_link", "uri": "test://data", "name": "附件"},
            ],
            "structuredContent": {"nested": [1, False, None]},
            "isError": business_error,
        }
    )

    async def scenario():
        async with env.start() as (executor, _):
            result = await submit(env, executor)
            assert result["status"] == ("failed" if business_error else "completed")
            assert result["value"] == env.session.result.model_dump(mode="json", by_alias=True, exclude_unset=True)
            if business_error:
                assert result["error"]["code"] == "mcp_tool_error"

    asyncio.run(scenario())


def test_input_required_is_observed_without_followup(environment):
    env = environment
    env.session.result = InputRequiredResult(request_state="opaque-secret")

    async def scenario():
        async with env.start() as (executor, _):
            result = await submit(env, executor)
            assert result["error"]["code"] == "mcp_input_required"
            assert "opaque-secret" not in repr(result)
            assert len(env.session.calls) == 1

    asyncio.run(scenario())


@pytest.mark.parametrize("mode", ["arguments", "reject", "closed", "stopped"])
def test_rejected_calls_do_not_reach_server_and_after_hook_observes_failure(environment, mode):
    env = environment

    async def scenario():
        async with env.start() as (executor, instance):
            observed = []

            async def before(request):
                if mode == "reject":
                    raise ToolRejected("拒绝本次执行")

            async def after(request):
                observed.append(executor.current_state.get(env.ctx, request))

            for slot, handler, name in [(executor.before, before, "before"), (executor.after, after, "after")]:
                identity = Id(f"dev.mcp:handlers/{name}")
                env.registry.register_many(component_entries(identity, handler, handler, provider="test"))
                slot.connect(ExecutionPlug(identity, handler))
            if mode == "closed":
                await instance.aclose()
            if mode == "stopped":
                env.clients.stop_accepting()
            result = await submit(env, executor, {"text": 42} if mode == "arguments" else None)
            assert result["status"] == "failed" and env.session.calls == []
            assert observed[0]["result"] == result
            assert env.closed == []

    asyncio.run(scenario())


@pytest.mark.parametrize("mode", ["timeout", "cancel", "server_timeout"])
def test_timeout_and_cancellation_finish_borrowed_call_without_replay(environment, mode):
    env = environment
    env.session.wait = True
    if mode == "server_timeout":
        env.config["servers"]["local"]["timeout"] = {"execution": 0.02}
        env.ctx.set(CONFIG_STATE, env.config)

    async def scenario():
        async with env.start(timeout=0.02 if mode == "timeout" else 10) as (executor, _):
            task = asyncio.create_task(submit(env, executor))
            await env.session.entered.wait()
            if mode == "timeout":
                assert (await task)["error"]["code"] == "timeout"
            elif mode == "server_timeout":
                assert (await task)["error"]["code"] == "mcp_timeout"
            else:
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
                result = cast(dict, executor.output_state.get(env.ctx, ExecutionRequest("run")))
                assert result["status"] == "cancelled"
                assert result["results"][0]["error"]["code"] == "cancelled"
            assert env.session.finished.is_set() and len(env.session.calls) == 1
            assert env.closed == []
        assert env.closed == ["local"]
        assert not [task for task in asyncio.all_tasks() if task.get_name().startswith("aurora-mcp:")]

    asyncio.run(scenario())

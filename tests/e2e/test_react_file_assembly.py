"""版本 2 文件驱动真实 ReAct、模型资源和静态/MCP 工具集合。"""

import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
from types import SimpleNamespace

import tomli_w
from aurora_control import ExecutionPlug, ExecutionRequest, component_entries
from aurora_core import Id
from aurora_core.ctx import StateKey
from aurora_core.discovery import Plugin
from aurora_core.registry import RegistryEntry
from aurora_host import Host, read_assembly
from aurora_model.registry import ADAPTERS, ModelAdapter
from aurora_model.testing import FakeModel, FakeReply
from aurora_tools.execution import TOOLS, ToolInstance, ToolSpec
from mcp.types import CallToolResult, ListToolsResult, ServerCapabilities, Tool, ToolsCapability

STATE = Id("dev.graph:state/work")
TOOL = Id("dev.graph:tools/local")
COMPONENT = Id("dev.graph:components/local")
ADAPTER = Id("dev.graph:adapters/chat")


def state(part, *, fixed=False):
    return {"key": str(STATE), "scope": "instance" if fixed else "run", "location": {"part": part}}


def reference(instance, export):
    return {"instance": instance, "export": export}


def graph():
    instances = {
        "loader": {"plugin": "aurora_config", "component": "configuration"},
        "clients": {"plugin": "aurora_mcp", "component": "clients", "depends_on": ["loader"]},
        "catalog": {
            "plugin": "aurora_mcp.tools",
            "component": "catalog",
            "resources": {"clients": reference("clients", "clients")},
            "depends_on": ["clients"],
        },
        "react": {
            "plugin": "aurora_agent.react",
            "component": "react",
            "states": {
                **{
                    name: state(name, fixed=name in ("inbox", "progress", "runtime"))
                    for name in ("inbox", "progress", "runtime", "batch", "decision")
                },
                "config": {"key": "org.aurora.agent:state/react/config", "scope": "instance"},
            },
            "depends_on": ["loader"],
        },
        "executor": {
            "plugin": "aurora_tools",
            "component": "executor",
            "states": {
                "input": state("tool_input"),
                "output": state("tool_output"),
                "current": state("current"),
                "config": {"key": "org.aurora.tools:state/executor/config", "scope": "instance"},
            },
            "depends_on": ["loader"],
        },
        "defaults": {
            "plugin": "aurora_agent.react_defaults",
            "component": "defaults",
            "states": {
                **{
                    name: state(name, fixed=name == "context")
                    for name in (
                        "context",
                        "batch",
                        "decision",
                        "model_input",
                        "model_output",
                        "tool_input",
                        "tool_output",
                    )
                },
                "config": {"key": "org.aurora.agent:state/react_defaults/config", "scope": "instance"},
            },
            "resources": {"agent": reference("react", "agent"), "tools": reference("executor", "executor")},
            "depends_on": ["loader"],
        },
    }
    for name in ("first", "second"):
        instances[name] = {
            "plugin": "aurora_model",
            "component": "chat",
            "options": {"profile": name},
            "states": {"profiles": {"key": "org.aurora.model:state/config", "scope": "instance"}},
            "resources": {"catalog": reference("catalog", "catalog")},
            "depends_on": ["loader", "catalog"],
        }
        instances[name + "_call"] = {
            "plugin": "aurora_agent.model",
            "component": "model_call",
            "states": {
                "input": state("model_input"),
                "output": state("model_output"),
                "config": {"key": "org.aurora.agent:state/model_call/config", "scope": "instance"},
            },
            "resources": {"chat": reference(name, "model")},
            "depends_on": [name],
        }
    for name in ("static", "remote"):
        instances[name] = {
            "plugin": "aurora_tools",
            "component": "collection",
            "options": {
                "owner": "example",
                "instance_pattern": "{collection}/{name}",
                "location_field": "member",
                "tools": [{"id": str(TOOL)}] if name == "static" else [],
                "include": ["org.aurora.mcp:tools/*"] if name == "remote" else [],
            },
            "states": {"input": state("member_input"), "output": state("member_output")},
            "depends_on": ["catalog", "executor"],
            "resources": {}
            if name == "static"
            else {"catalog": reference("catalog", "catalog"), "tools": {"clients": reference("clients", "clients")}},
        }
    declaration = {
        "schema_version": 2,
        "plugins": [
            "fixture",
            "aurora_config",
            "aurora_model",
            "aurora_model.configuration",
            "aurora_agent.model",
            "aurora_agent.react",
            "aurora_agent.react_defaults",
            "aurora_agent.configuration",
            "aurora_tools",
            "aurora_tools.configuration",
            "aurora_mcp",
            "aurora_mcp.tools",
        ],
        "instances": instances,
        "connections": [],
        "collection_connections": [],
    }

    def connect(instance, identity, target, slot, priority=0):
        declaration["connections"].append(
            {
                "plug": {"instance": instance, "id": identity},
                "slot": {"instance": target, "id": slot},
                "priority": priority,
            }
        )

    for instance, prefix, phases in (
        ("loader", "org.aurora.config:handlers/load", {"config": ""}),
        (
            "clients",
            "org.aurora.mcp:handlers/",
            {"config": "configure", "prepare": "prepare", "stop": "stop", "clean": "clean"},
        ),
        ("catalog", "org.aurora.mcp:handlers/tools/", {"prepare": "prepare"}),
        ("react", "org.aurora.agent:handlers/react/", {"config": "configure"}),
        ("defaults", "org.aurora.agent:handlers/react_defaults/", {"config": "configure"}),
        ("executor", "org.aurora.tools:handlers/executor/", {"config": "configure"}),
        *(
            (name, "org.aurora.model:handlers/chat/", {"prepare": "prepare", "clean": "clean"})
            for name in ("first", "second")
        ),
        *(
            (name + "_call", "org.aurora.agent:handlers/model_call/", {"config": "configure"})
            for name in ("first", "second")
        ),
        *(
            (name, "org.aurora.tools:handlers/collection/", {"prepare": "prepare", "clean": "clean"})
            for name in ("static", "remote")
        ),
    ):
        for phase, method in phases.items():
            connect(instance, prefix + method, instance, "org.aurora.core:lifecycle/" + phase)
    for instance, identity, phase, priority in (
        ("defaults", "org.aurora.agent:handlers/react/build_prompt/execute", "prepare", 10),
        ("first_call", "org.aurora.agent:handlers/model_call/execute", "infer", 0),
        ("defaults", "org.aurora.agent:handlers/react/interpret_response/execute", "infer", 10),
        ("executor", "org.aurora.tools:components/executor/execute", "act", 0),
        ("defaults", "org.aurora.agent:handlers/react/record_observation/execute", "observe", 10),
    ):
        connect(instance, identity, "react", "org.aurora.agent:react/" + phase, priority)
    declaration["collection_connections"] = [
        {"collection": name, "slot": {"instance": "executor", "id": "org.aurora.tools:components/executor/children"}}
        for name in ("static", "remote")
    ]
    return declaration


def test_file_react_swaps_infer_and_expands_mcp_members_with_single_resource_owners(tmp_path, monkeypatch):
    models, events = [], []

    class Model(FakeModel):
        async def aclose(self):
            events.append("model_closed")
            await super().aclose()

    async def create_model(config, *, api_key=None):
        assert api_key == "fixture-secret"
        replies = iter(
            (
                FakeReply(
                    tool_calls=(
                        {"id": "one", "name": "local", "arguments": {}},
                        {"id": "two", "name": "remote_echo", "arguments": {}},
                    )
                ),
                FakeReply((config.model,)),
            )
        )
        client = Model(lambda request: next(replies))
        models.append(client)
        return client

    async def execute(request):
        pass

    async def create_tool(*, ctx, input_state, output_state, instance_id, owner, resources, **kwargs):
        assert owner == "example"

        async def run(request):
            output_state.set(ctx, request, {"local": True})

        async def close():
            events.append("tool_closed")

        return ToolInstance(
            ExecutionPlug(COMPONENT, run, {"input": input_state, "output": output_state}, instance_id=instance_id),
            close,
        )

    fixture = Plugin(
        "fixture",
        (
            RegistryEntry(STATE, "state_key", StateKey(lambda value: None), "fixture"),
            RegistryEntry(ADAPTER, "adapter", ModelAdapter("chat", create_model), "fixture", register_to=ADAPTERS),
            *component_entries(COMPONENT, create_tool, execute, provider="fixture"),
            RegistryEntry(
                TOOL,
                "tool",
                ToolSpec(
                    COMPONENT,
                    {"name": "local", "description": "本地工具", "parameters": {"type": "object"}},
                    factory=create_tool,
                ),
                "fixture",
                register_to=TOOLS,
            ),
        ),
    )

    async def list_tools(**kwargs):
        return ListToolsResult(tools=[Tool(name="echo", input_schema={"type": "object"})])

    async def call_tool(name, arguments, **kwargs):
        events.append("remote_called")
        return CallToolResult(content=[], structured_content={"remote": True})

    @asynccontextmanager
    async def open_client(config, resolve_env, negotiation, **kwargs):
        events.append("mcp_opened")
        try:
            yield SimpleNamespace(
                protocol_version="2026-07-28",
                server_capabilities=ServerCapabilities(tools=ToolsCapability()),
                session=SimpleNamespace(list_tools=list_tools, call_tool=call_tool),
            )
        finally:
            events.append("mcp_closed")

    monkeypatch.setattr("aurora_mcp.transports.open_client", open_client)
    monkeypatch.setenv("GRAPH_CREDENTIAL", "fixture-secret")

    async def run(name, declaration):
        data = tmp_path / name
        for owner, filename, values in (
            (
                "org.aurora.model",
                "profiles.toml",
                {
                    key: {"adapter": str(ADAPTER), "model": key, "credential": "GRAPH_CREDENTIAL"}
                    for key in ("first", "second")
                },
            ),
            ("org.aurora.model", "bindings.toml", {}),
            (
                "org.aurora.mcp",
                "plugin.config.toml",
                {
                    "schema_version": 2,
                    "servers": {
                        "test": {
                            "type": "remote",
                            "url": "http://localhost/mcp",
                            "tools": {"include": ["echo"], "aliases": {"echo": "remote_echo"}},
                        }
                    },
                },
            ),
        ):
            path = data / "config" / owner / filename
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(tomli_w.dumps(values))
        path = data / "assembly.toml"
        path.write_text(tomli_w.dumps(declaration))
        host = Host.create(read_assembly(path), [fixture], data, workspace_root=tmp_path)
        assert not host.graph.members
        count = len(models)
        resource = host.graph.instances[name].exports.resources["model"]
        try:
            await host.start()
            assert len(models) == count + 2
            assert host.graph.instances[name + "_call"].instance.client is resource
            assert set(host.graph.members) == {"static", "remote"}
            assert {member for group in host.graph.members.values() for member in group} == {
                "static/local",
                "remote/remote_echo",
            }
            agent = host.graph.instances["react"].instance
            request = ExecutionRequest(name)
            agent.inbox.set(host.ctx, request, [{"id": name, "sequence": 1, "payload": "调用工具"}])
            await host.run(agent.execute, request)
            defaults = host.graph.instances["defaults"].instance
            context = defaults.context_state.get(host.ctx, request)
            assert context["messages"][-1]["content"] == name
            assert [item["role"] for item in context["messages"]] == ["user", "assistant", "tool", "tool", "assistant"]
            assert len(host.graph.connections) == len(declaration["connections"]) + 2
        finally:
            await host.stop()
        assert all(client.closed for client in models[count:])
        assert events.count("mcp_closed") == events.count("mcp_opened")
        assert "fixture-secret" not in (data / "framework/ctx.json").read_text()

    declaration = graph()
    asyncio.run(run("first", declaration))
    swapped = deepcopy(declaration)
    connection = next(
        item
        for item in swapped["connections"]
        if item["plug"]["instance"] == "first_call" and item["slot"]["id"] == "org.aurora.agent:react/infer"
    )
    connection["plug"]["instance"] = "second_call"
    asyncio.run(run("second", swapped))
    assert events.count("remote_called") == 2
    assert events.count("tool_closed") == 2
    assert events.count("model_closed") == 4
    assert events.count("mcp_closed") == 2

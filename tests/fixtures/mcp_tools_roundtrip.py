"""本机 MCP 工具桥验收；支持无 world 宿主和使用假模型的默认 bot。"""

import argparse
import asyncio
import json
import socket
import sys
from pathlib import Path
from typing import cast

import tomli_w
import uvicorn
from aurora_adapter.mcp import CLIENT_STATUS, PROTOCOL_VERSION, MCPClients
from aurora_adapter.mcp.catalog import automatic_name
from aurora_adapter.mcp.tools import MCPTools
from aurora_agent.tools import ToolExecutor, ToolSpec
from aurora_config import configuration_component
from aurora_control import ExecutionRequest, StateBinding
from aurora_core import Id
from aurora_core.bootstrap import bootstrap
from aurora_core.ctx import Context, StateKey
from aurora_core.discovery import load_plugins, register_plugins
from aurora_core.hooks import HookConnections
from aurora_core.lifecycle import Lifecycle, install_lifecycle_slots
from aurora_core.persistence import ContextPersistence
from aurora_core.registry import RegistryEntry
from aurora_core.storage import StorageService
from mcp.server import MCPServer

STATE = Id("dev.mcp:state/work")


def echo_service(record) -> MCPServer:
    """两种传输共用同一工具声明和执行结果。"""
    service = MCPServer("aurora-tools-test")

    @service.tool()
    def echo(text: str) -> dict[str, str]:
        """返回结构化测试文本；指定值触发业务失败。"""
        record(text)
        if text == "fail":
            raise ValueError("测试业务错误")
        return {"text": text}

    return service


async def run(
    root: Path,
    *,
    with_bot: bool = False,
    protocol: str = PROTOCOL_VERSION,
    transport: str = "remote",
    automatic: bool = False,
) -> dict:
    """通过真实本机 HTTP 或 stdio 完成工具及假模型默认装配验收。"""
    tool_name = automatic_name("local", "echo") if automatic else "local_echo"
    tool_id = Id(f"org.aurora.adapter:tools/mcp/{tool_name}")
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    calls = []
    service = echo_service(calls.append)
    listener = None
    server = None
    serving = None
    if transport == "remote":
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(service.streamable_http_app(), log_level="critical", lifespan="on"))
        serving = asyncio.create_task(server.serve(sockets=[listener]))
        declaration = {"type": "remote", "url": f"http://127.0.0.1:{port}/mcp"}
    else:
        (root / "calls.jsonl").write_text("", encoding="utf-8")
        declaration = {
            "type": "local",
            "command": [sys.executable, str(Path(__file__).resolve()), str(root), "--stdio-server"],
        }

    def observed_calls():
        return (
            calls
            if transport == "remote"
            else [json.loads(line) for line in (root / "calls.jsonl").read_text(encoding="utf-8").splitlines()]
        )

    try:
        if server is not None and serving is not None:
            async with asyncio.timeout(10):
                while not server.started:
                    if serving.done():
                        await serving
                        raise RuntimeError("本机 MCP 服务未启动")
                    await asyncio.sleep(0.01)
        registry = bootstrap()
        install_lifecycle_slots(registry)
        enabled = ["aurora_config", "aurora_adapter.mcp", "aurora_agent.tools", "aurora_adapter.mcp.tools"]
        if with_bot:
            enabled += [
                "aurora_adapter.model",
                "aurora_agent.model",
                "aurora_agent.react",
                "aurora_agent.react_defaults",
                "aurora_bot.assembly",
            ]
        register_plugins(registry, load_plugins(enabled=enabled))
        registry.register(RegistryEntry(STATE, "state_key", StateKey(persistent=False), "test"))
        ctx, hooks, storage = Context(registry), HookConnections(registry), StorageService(root)

        def config_file(relative, value):
            path = storage.configuration_directory() / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(tomli_w.dumps(value), encoding="utf-8")

        config_file(
            "org.aurora.adapter/mcp.toml",
            {
                "schema_version": 2,
                "servers": {
                    "local": {
                        **declaration,
                        "protocol": protocol,
                        "required_capabilities": ["tools"],
                        "timeout": {"catalog": 2, "execution": 2},
                        "tools": {} if automatic else {"include": ["echo"], "aliases": {"echo": "local_echo"}},
                    }
                },
            },
        )
        clients = MCPClients(ctx, hooks, workspace_root=root)
        bridge = MCPTools(registry, ctx, hooks, clients)
        components = [bridge.component(), clients.component(), configuration_component(registry, ctx, hooks, storage)]
        assembly = None
        if with_bot:
            from aurora_adapter.model.config import ADAPTERS, ModelAdapter
            from aurora_adapter.model.testing import FakeModel, FakeReply
            from aurora_bot.assembly import DefaultAssembly

            async def model_factory(config, *, api_key=None):
                assert bridge.prepared and registry.get(tool_id)

                def reply(request):
                    if any(message["role"] == "tool" for message in request["messages"]):
                        return FakeReply(("完成",))
                    assert request["tools"][0]["name"] == tool_name
                    return FakeReply(
                        tool_calls=({"id": "remote-call", "name": tool_name, "arguments": {"text": "你好"}},)
                    )

                return FakeModel(reply)

            adapter = Id("dev.mcp:adapters/fake")
            registry.register(
                RegistryEntry(adapter, "adapter", ModelAdapter("chat", model_factory), "test", register_to=ADAPTERS)
            )
            config_file("org.aurora.adapter/model/profiles.toml", {"test": {"adapter": str(adapter), "model": "fake"}})
            config_file("org.aurora.adapter/model/bindings.toml", {"reasoning": "test"})
            config_file(
                "org.aurora.bot/config.toml",
                {
                    "instance_id": "main",
                    "model_role": "reasoning",
                    "streaming": False,
                    "tools": [{"tool": str(tool_id), "instance_id": "echo"}],
                },
            )
            assembly = DefaultAssembly(registry=registry, ctx=ctx, hooks=hooks, storage=storage)
            components[0:0] = assembly.components(depends_on=(bridge.instance_id,))
        host = Lifecycle(
            ctx, hooks, components, persistence=ContextPersistence(ctx, storage.snapshot_store()), storage=storage
        )
        await host.start()
        client_status = cast(
            dict, ctx.get(CLIENT_STATUS, location={"owner": clients.instance_id, "connection_id": "local"})
        )
        assert client_status["configured_protocol"] == protocol
        assert client_status["negotiated_protocol"] == ("2025-11-25" if protocol == "legacy" else PROTOCOL_VERSION)
        try:
            if assembly is not None:
                assert assembly.agent is not None and assembly.defaults is not None
                request = ExecutionRequest("roundtrip")
                assembly.agent.inbox.set(ctx, request, [{"id": "guide", "sequence": 1, "payload": "回显你好"}])
                await host.run(assembly.activate, request)
                messages = cast(dict, assembly.defaults.context_state.get(ctx, request))["messages"]
                observed = json.loads(next(message["content"] for message in messages if message["role"] == "tool"))
                assert observed["status"] == "completed"
                assert observed["value"]["structuredContent"] == {"text": "你好"}
                assert messages[-1]["content"] == "完成" and observed_calls() == ["你好"]
            else:

                def state(part):
                    return StateBinding(STATE, (("part", part),))

                executor = ToolExecutor(
                    ctx,
                    registry,
                    hooks,
                    request_state=state("calls"),
                    output_state=state("results"),
                    current_state=state("current"),
                    timeout=3,
                )
                spec = cast(ToolSpec, registry.get(tool_id).target)
                assert spec.factory is not None
                tool = await spec.factory(
                    ctx=ctx,
                    storage=storage,
                    instance_id="echo",
                    input_state=state("input"),
                    output_state=state("output"),
                    config={},
                )
                executor.connect(tool_id, tool.plug)
                try:
                    request = ExecutionRequest("roundtrip")
                    executor.request_state.set(
                        ctx,
                        request,
                        {
                            "turn_id": "turn",
                            "calls": [
                                {"id": "ok", "name": tool_name, "arguments": {"text": "你好"}},
                                {"id": "bad", "name": tool_name, "arguments": {"text": "fail"}},
                            ],
                        },
                    )
                    await host.run(executor.execute, request)
                    results = cast(dict, executor.output_state.get(ctx, request))["results"]
                    assert results[0]["status"] == "completed"
                    assert results[0]["value"]["structuredContent"] == {"text": "你好"}
                    assert results[1]["error"]["code"] == "mcp_tool_error"
                    assert results[1]["value"]["content"] and observed_calls() == ["你好", "fail"]
                    assert ctx.snapshot(persistent_only=True).records == ()
                finally:
                    if tool.aclose:
                        await tool.aclose()
        finally:
            await host.stop()
        assert not [task for task in asyncio.all_tasks() if task.get_name().startswith("aurora-mcp:")]
        return {"tool_bridge": True, "default_bot": with_bot, "calls": len(observed_calls())}
    finally:
        if server is not None and serving is not None and listener is not None:
            server.should_exit = True
            await serving
            listener.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--bot", action="store_true")
    parser.add_argument("--protocol", choices=["legacy", "auto", PROTOCOL_VERSION], default=PROTOCOL_VERSION)
    parser.add_argument("--transport", choices=["remote", "local"], default="remote")
    parser.add_argument("--stdio-server", action="store_true")
    parser.add_argument("--automatic", action="store_true")
    args = parser.parse_args()
    if args.stdio_server:

        def record(text):
            with (args.root / "calls.jsonl").open("a", encoding="utf-8") as output:
                output.write(json.dumps(text, ensure_ascii=False) + "\n")

        echo_service(record).run()
    else:
        print(
            json.dumps(
                asyncio.run(
                    run(
                        args.root,
                        with_bot=args.bot,
                        protocol=args.protocol,
                        transport=args.transport,
                        automatic=args.automatic,
                    )
                ),
                ensure_ascii=False,
            )
        )

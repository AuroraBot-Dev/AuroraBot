"""通过本机真实 HTTP 服务验收独立 MCP 宿主；仅使用测试工具与内存资源。"""

import asyncio
import json
import socket
import sys
from pathlib import Path
from typing import cast

import uvicorn
from aurora_adapter.mcp import CLIENT_STATUS, CONFIG_STATE, PROTOCOL_VERSION, MCPClientError, MCPClients
from aurora_config import configuration_component
from aurora_core.bootstrap import bootstrap
from aurora_core.ctx import Context
from aurora_core.discovery import load_plugins, register_plugins
from aurora_core.hooks import HookConnections
from aurora_core.lifecycle import Lifecycle, install_lifecycle_slots
from aurora_core.persistence import ContextPersistence
from aurora_core.storage import StorageService
from mcp.server import MCPServer


async def run(root: Path) -> dict:
    """启用声明配置，读取能力与资源，确认关闭后不再借用且配置不持久化。"""
    service = MCPServer("aurora-local-test")

    @service.tool()
    def echo(text: str) -> str:
        """返回测试文本。"""
        return text

    @service.resource("test://value")
    def value() -> str:
        """提供确定的测试资源。"""
        return "本机资源"

    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(service.streamable_http_app(), log_level="critical", lifespan="on"))
    serving = asyncio.create_task(server.serve(sockets=[listener]))
    try:
        async with asyncio.timeout(10):
            while not server.started:
                if serving.done():
                    await serving
                    raise RuntimeError("本机 MCP 测试服务未启动")
                await asyncio.sleep(0.01)
        registry = bootstrap()
        install_lifecycle_slots(registry)
        register_plugins(registry, load_plugins(enabled=["aurora_config", "aurora_adapter.mcp"]))
        ctx, hooks, storage = Context(registry), HookConnections(registry), StorageService(root)
        config = storage.configuration_directory() / "org.aurora.adapter" / "mcp.toml"
        config.parent.mkdir(parents=True, exist_ok=True)
        text = (
            f'schema_version = 2\n[servers.local]\ntype = "remote"\nprotocol = "2026-07-28"\nurl = "http://127.0.0.1:{port}/mcp"\n'
            'required_capabilities = ["tools", "resources"]\ntimeout.execution = 1.0\n'
        )
        config.write_text(text, encoding="utf-8")
        owner = MCPClients(ctx, hooks)
        store = storage.snapshot_store()
        host = Lifecycle(
            ctx,
            hooks,
            [owner.component(), configuration_component(registry, ctx, hooks, storage)],
            persistence=ContextPersistence(ctx, store, interval=60),
            storage=storage,
        )
        await host.start()
        try:
            observed = cast(
                dict, ctx.get(CLIENT_STATUS, location={"owner": "aurora_adapter/mcp", "connection_id": "local"})
            )
            assert observed["phase"] == "ready" and observed["accepting"]
            async with owner.connection("local") as client:
                assert client.protocol_version == PROTOCOL_VERSION
                assert [tool.name for tool in (await client.list_tools()).tools] == ["echo"]
                answer = await client.call_tool("echo", {"text": "连接正常"})
                assert not answer.is_error
                assert answer.content[0].model_dump()["text"] == "连接正常"
                resource = await client.read_resource("test://value")
                assert resource.contents[0].model_dump()["text"] == "本机资源"
            assert ctx.snapshot(persistent_only=True).records == ()
            ctx.set(CONFIG_STATE, {"schema_version": 2, "servers": {}})
            assert config.read_text(encoding="utf-8") == text
            server.should_exit = True
            await serving
            with_error = False
            try:
                async with owner.connection("local") as client:
                    await client.list_tools()
            except MCPClientError as error:
                with_error = error.code == "request_failed"
            assert with_error
            assert (
                cast(dict, ctx.get(CLIENT_STATUS, location={"owner": "aurora_adapter/mcp", "connection_id": "local"}))[
                    "error"
                ]
                == "request_failed"
            )
        finally:
            await host.stop()
        assert store.load() == ()
        assert config.read_text(encoding="utf-8") == text
        assert not [task for task in asyncio.all_tasks() if task.get_name().startswith("aurora-mcp:")]
        return {"protocol": PROTOCOL_VERSION, "roundtrip": True, "disconnect_reported": True, "snapshot_empty": True}
    finally:
        server.should_exit = True
        await serving
        listener.close()


if __name__ == "__main__":
    print(json.dumps(asyncio.run(run(Path(sys.argv[1]))), ensure_ascii=False))

"""验证两个工作台的编辑冲突、单端断线和宿主重启边界。"""

import asyncio
import json
from dataclasses import replace
from pathlib import Path

from aiohttp import ClientSession, WSMsgType, web
from aurora_api.protocol import SUBSCRIBE, UNSUBSCRIBE
from aurora_api.server import serve
from aurora_bot.assembly_config import AGENTS, MESSAGES, RUN, WORK
from aurora_bot.conversation import CONVERSATION
from aurora_config import CONFIGURATION
from aurora_core import entry_from
from aurora_core.ctx import StateKey
from aurora_core.ids import Id
from aurora_core.registry import RegistryEntry
from test_default_assembly import seed, setup

ROOT = Path(__file__).resolve().parents[2]
SHARED = Id("dev.recovery:state/shared")
EPHEMERAL = Id("dev.recovery:state/ephemeral")


class ClientLink:
    """只隔离一个客户端的 HTTP/WS；首次提交在接纳后丢弃回执。"""

    def __init__(self, target, session):
        self.target = target
        self.session = session
        self.paused = False
        self.drop_submit = True
        self.submissions = 0
        self.sockets = set()

    async def handle(self, request):
        if self.paused:
            return web.json_response({"error": {"code": "offline", "message": "验收链路断开"}}, status=503)
        target = self.target + request.path_qs
        if request.headers.get("Upgrade", "").lower() == "websocket":
            downstream = web.WebSocketResponse()
            await downstream.prepare(request)
            self.sockets.add(downstream)
            try:
                async with self.session.ws_connect(target) as upstream:

                    async def forward(source, destination):
                        async for message in source:
                            if message.type == WSMsgType.TEXT:
                                await destination.send_str(message.data)

                    tasks = [
                        asyncio.create_task(forward(downstream, upstream)),
                        asyncio.create_task(forward(upstream, downstream)),
                    ]
                    try:
                        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                    finally:
                        for task in tasks:
                            task.cancel()
                        await asyncio.gather(*tasks, return_exceptions=True)
            finally:
                self.sockets.discard(downstream)
                await downstream.close()
            return downstream
        async with self.session.request(
            request.method, target, data=await request.read(), headers={"Content-Type": "application/json"}
        ) as response:
            body = await response.read()
            if request.path == "/conversation/submit":
                self.submissions += 1
                if self.drop_submit:
                    assert response.status == 200
                    self.drop_submit = False
                    self.paused = True
                    await asyncio.gather(*(socket.close() for socket in tuple(self.sockets)))
                    assert request.transport is not None
                    request.transport.close()
            return web.Response(body=body, status=response.status, content_type="application/json")


def make_host(root, *, behavior):
    host, _, ctx, registry, clients, _, events, _ = setup(root, behavior=behavior)
    registry.register_many(
        entry_from(target, provider="test")
        for target in (ctx.get, ctx.set, ctx.delete, ctx.list, ctx.subscribe, ctx.unsubscribe)
    )
    registry.register(RegistryEntry(SHARED, "state_key", StateKey(), "test"))
    registry.register(RegistryEntry(EPHEMERAL, "state_key", StateKey(persistent=False), "test"))
    active = set()

    def subscribe(callback, **filters):
        handle = ctx.subscribe(callback, **filters)
        active.add(handle)
        return handle

    def unsubscribe(handle):
        active.remove(handle)
        return ctx.unsubscribe(handle)

    registry.replace(replace(registry.get(SUBSCRIBE), target=subscribe))
    registry.replace(replace(registry.get(UNSUBSCRIBE), target=unsubscribe))
    return host, ctx, registry, clients, events, active


def api(registry, port=0):
    return serve(
        registry,
        keys=[AGENTS, MESSAGES, RUN, WORK, SHARED, EPHEMERAL],
        endpoints=[CONVERSATION, CONFIGURATION],
        port=port,
    )


def test_two_workbenches_reconcile_without_replaying_after_disconnect_and_restart(tmp_path):
    async def scenario():
        host, ctx, registry, clients, events, active = make_host(tmp_path, behavior="wait")
        await host.start(configure=lambda: seed(ctx))
        ctx.set(EPHEMERAL, "只属于第一个宿主")
        server = api(registry)
        url = await server.__aenter__()
        process = None
        runner = None
        try:
            async with ClientSession() as session:
                link = ClientLink(url, session)
                app = web.Application()
                app.router.add_route("*", "/{path:.*}", link.handle)
                runner = web.AppRunner(app)
                await runner.setup()
                await web.TCPSite(runner, "127.0.0.1", 0).start()
                relay_url = f"http://127.0.0.1:{runner.addresses[0][1]}"
                process = await asyncio.create_subprocess_exec(
                    "node",
                    "--experimental-ffi",
                    str(ROOT / "apps/aurora_tui/tests/recovery-process.ts"),
                    relay_url,
                    url,
                    cwd=ROOT,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                assert process.stdin and process.stdout and process.stderr

                async def checkpoint(event):
                    assert process and process.stdout and process.stderr
                    line = await asyncio.wait_for(process.stdout.readline(), timeout=25)
                    assert line, (await process.stderr.read()).decode("utf-8")
                    assert json.loads(line) == {"event": event}

                async def proceed():
                    assert process and process.stdin
                    process.stdin.write(b"continue\n")
                    await process.stdin.drain()

                await checkpoint("disconnected")
                assert len(active) == 1 and link.paused
                assert events.count("tool.executed") == 1 and "tool.cancelled" not in events
                assert link.submissions == 1
                link.paused = False
                await proceed()
                await checkpoint("restart")
                assert len(active) == 2 and link.submissions == 1
                await server.__aexit__(None, None, None)
                assert not active
                await host.stop()
                assert events.index("tool.cancelled") < events.index("tool.closed") < events.index("model.closed")
                assert events.count("tool.executed") == events.count("tool.cancelled") == 1
                assert all(client.closed for client in clients)
                await proceed()
                await checkpoint("offline")

                host, ctx, registry, clients, events, active = make_host(tmp_path, behavior="quiet")
                await host.start()
                assert ctx.list(key=EPHEMERAL) == ()
                assert ctx.get(SHARED, location={"part": "current"}) == "断线期间更新"
                assert ctx.get(AGENTS, location={"instance_id": "main", "part": "last_close"}) == "工具最后写入"
                server = api(registry, port=int(url.rsplit(":", 1)[1]))
                assert await server.__aenter__() == url
                await proceed()
                await checkpoint("restored")
                assert len(active) == 2 and link.submissions == 1
                assert all(not client.requests for client in clients)
                assert "tool.executed" not in events
                await proceed()
                await checkpoint("one_closed")
                async with asyncio.timeout(5):
                    while len(active) != 1:
                        await asyncio.sleep(0.01)
                assert link.submissions == 1
                assert sum(len(client.requests) for client in clients) == 1
                await proceed()
                output, errors = await asyncio.wait_for(process.communicate(), timeout=15)
                assert process.returncode == 0, errors.decode("utf-8") + output.decode("utf-8")
                assert json.loads(output) == {"event": "complete"}
                async with asyncio.timeout(5):
                    while active:
                        await asyncio.sleep(0.01)
                assert ctx.get(SHARED, location={"part": "current"}) == "另一端退出后仍可编辑"
        finally:
            if process is not None and process.returncode is None:
                process.kill()
                await process.communicate()
            if runner is not None:
                await runner.cleanup()
            await server.__aexit__(None, None, None)
            await host.stop()
        assert not active and all(client.closed for client in clients)
        assert "tool.executed" not in events

    asyncio.run(scenario())

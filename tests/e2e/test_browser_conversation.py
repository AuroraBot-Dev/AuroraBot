"""浏览器来源的认证覆盖默认装配、直接交流和显式取消。"""

import asyncio
import base64

from aiohttp import ClientSession
from aurora_adapter.model.testing import FakeReply
from aurora_api.access import AccessPolicy
from aurora_api.server import serve
from aurora_bot.conversation import CONVERSATION
from aurora_config import CONFIGURATION
from aurora_control import ExecutionRequest
from test_default_assembly import seed, setup


def test_browser_file_larger_than_default_body_limit_reaches_model(tmp_path):
    async def scenario():
        host, assembly, ctx, registry, clients, _, _, _ = setup(tmp_path)
        await host.start(configure=lambda: seed(ctx))
        clients[0].respond = lambda _: FakeReply(("已读取",), reasoning=("分析附件",))
        try:
            async with serve(registry, keys=[], endpoints=[CONVERSATION], port=0) as url, ClientSession() as http:
                async with http.post(url + "/conversation/info", json={}) as response:
                    info = (await response.json())["result"]
                data = base64.b64encode(b"x" * (1024 * 1024)).decode()
                message = {
                    "session_id": info["session_id"],
                    "instance_id": "main",
                    "request_id": "file",
                    "text": "",
                    "files": [{"name": "large.pdf", "media_type": "application/pdf", "data": data}],
                }
                async with http.post(url + "/conversation/submit", json=message) as response:
                    assert response.status == 200, await response.text()
                if assembly.runtime.current:
                    await assembly.runtime.current.wait()
                content = clients[0].requests[0]["messages"][-1]["content"]
                assert content[0]["file"]["file_data"] == f"data:application/pdf;base64,{data}"
                async with http.post(
                    url + "/conversation/info", data='"' + data + '"', headers={"Content-Type": "application/json"}
                ) as response:
                    assert response.status == 413
        finally:
            await host.stop()

        restarted, restored, _, _, clients, _, _, _ = setup(tmp_path)
        await restarted.start()
        try:
            assert restored.defaults is not None
            context = restored.defaults._context(ExecutionRequest("inspect"))
            content = context["messages"][0]["content"]
            assert isinstance(content, list) and content[0]["type"] == "file"
            assert content[0]["file"].get("file_data", "").endswith(data)
            assert context["messages"][-1].get("reasoning_content") == "分析附件"
            assert clients[0].requests == []
        finally:
            await restarted.stop()

    asyncio.run(scenario())


def test_authenticated_browser_conversation_and_configuration(tmp_path):
    async def scenario():
        host, assembly, ctx, registry, _, _, events, entered = setup(tmp_path, behavior="wait")
        await host.start(configure=lambda: seed(ctx))
        token = "test-browser-product-token-1234567890"
        origin = "http://localhost:5173"
        access = AccessPolicy(token=token, allowed_origins=(origin,))
        try:
            async with (
                serve(registry, keys=[], endpoints=[CONVERSATION, CONFIGURATION], port=0, access=access) as url,
                ClientSession() as client,
            ):
                headers = {"Origin": origin, "Authorization": f"Bearer {token}"}

                async def call(path, body, *, authenticated=True, status=200):
                    async with client.post(
                        url + path, json=body, headers=headers if authenticated else {"Origin": origin}
                    ) as response:
                        assert response.status == status
                        assert response.headers["Access-Control-Allow-Origin"] == origin
                        return await response.json()

                for path in (
                    "/conversation/info",
                    "/conversation/submit",
                    "/conversation/cancel",
                    "/configuration/list",
                    "/configuration/save",
                ):
                    await call(path, {}, authenticated=False, status=401)
                    async with client.options(
                        url + path,
                        headers={
                            "Origin": origin,
                            "Access-Control-Request-Method": "POST",
                            "Access-Control-Request-Headers": "authorization,content-type",
                        },
                    ) as response:
                        assert response.status == 204
                assert assembly.runtime.current is None
                assert (await call("/configuration/list", {}))["result"]
                info = (await call("/conversation/info", {}))["result"]
                scope = {"session_id": info["session_id"], "instance_id": "main"}
                message = {**scope, "request_id": "browser-one", "text": "开始"}
                receipt = (await call("/conversation/submit", message))["result"]
                assert (await call("/conversation/submit", message))["result"] == receipt
                await asyncio.wait_for(entered.wait(), 2)
                assert events.count("tool.executed") == 1
                result = await call("/conversation/cancel", {**scope, "run_id": receipt["run_id"]})
                assert result["result"]["cancelled"] is True
                assert (await call("/conversation/query", {**scope, "request_id": "browser-one"}))["result"][
                    "run_status"
                ] == "cancelled"
                assert events.count("tool.cancelled") == 1
                assert token not in str(ctx.snapshot())
        finally:
            await host.stop()

    asyncio.run(scenario())

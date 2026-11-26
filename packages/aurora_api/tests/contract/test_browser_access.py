"""验证浏览器预检、认证与代理主机边界，不依赖真实模型。"""

import asyncio

import pytest
from aiohttp import ClientSession, WSServerHandshakeError
from aurora_api.access import AccessPolicy, token_from_env
from aurora_api.client import CtxClient, RemoteError
from aurora_api.server import serve
from test_ctx_api import PRIVATE, PUBLIC, make_host

TOKEN = "test-browser-access-token-1234567890"
ORIGIN = "http://localhost:5173"


@pytest.mark.parametrize(
    "values",
    [
        {"allowed_origins": (ORIGIN,)},
        {"allowed_hosts": ("api.example.test",)},
        {"token": "short"},
        {"token": TOKEN, "allowed_origins": ("*",)},
        {"token": TOKEN, "allowed_origins": ("null",)},
        {"token": TOKEN, "allowed_origins": (ORIGIN + "/",)},
        {"token": TOKEN, "allowed_origins": ("https://user:secret@example.test",)},
        {"token": TOKEN, "allowed_hosts": ("*.example.test",)},
        {"token": TOKEN, "allowed_hosts": ("api.example.test:443",)},
        {"token": TOKEN, "allowed_hosts": ()},
    ],
)
def test_unsafe_access_configuration_is_rejected(values):
    with pytest.raises((ValueError, TypeError)):
        AccessPolicy(**values)


def test_token_is_runtime_only_and_not_in_policy_repr(monkeypatch):
    monkeypatch.delenv("AURORA_TEST_ACCESS", raising=False)
    assert token_from_env(None) is None
    with pytest.raises(ValueError, match="未设置"):
        token_from_env("AURORA_TEST_ACCESS")
    monkeypatch.setenv("AURORA_TEST_ACCESS", TOKEN)
    assert token_from_env("AURORA_TEST_ACCESS") == TOKEN
    assert TOKEN not in repr(AccessPolicy(token=TOKEN))


def test_preflight_authentication_and_data_scope():
    async def scenario():
        registry, ctx, active, _ = make_host()
        ctx.set(PUBLIC, "公开")
        ctx.set(PRIVATE, "私有")
        policy = AccessPolicy(token=TOKEN, allowed_origins=(ORIGIN,))
        async with (
            serve(registry, keys=[], read_only_keys=[PUBLIC], port=0, access=policy) as url,
            ClientSession() as client,
        ):
            headers = {
                "Origin": ORIGIN,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "authorization,content-type",
            }
            async with client.options(url + "/ctx/get", headers=headers) as response:
                assert response.status == 204
                assert response.headers["Access-Control-Allow-Origin"] == ORIGIN
                assert "Origin" in response.headers["Vary"]
                assert "Access-Control-Allow-Credentials" not in response.headers
            for path, overrides in (
                ("/ctx/get", {"Access-Control-Request-Method": "DELETE"}),
                ("/ctx/get", {"Access-Control-Request-Headers": "X-Custom"}),
                ("/not-open", {}),
            ):
                async with client.options(url + path, headers={**headers, **overrides}) as response:
                    assert response.status == 403
            for authorization in (None, "Bearer wrong", "Bearer 中文"):
                headers = {"Origin": ORIGIN}
                if authorization:
                    headers["Authorization"] = authorization
                async with client.post(url + "/ctx/get", headers=headers, json={"key": str(PUBLIC)}) as response:
                    assert response.status == 401
                    assert response.headers["Access-Control-Allow-Origin"] == ORIGIN
                    assert (await response.json())["error"]["code"] == "unauthorized"
            headers = {"Origin": ORIGIN, "Authorization": f"Bearer {TOKEN}"}
            for override in (
                {"Origin": "null"},
                {"Origin": "http://localhost:5174"},
                {"Host": "evil.test"},
                {"Origin": "https://evil.test", "X-Forwarded-Host": "localhost"},
            ):
                async with client.post(
                    url + "/ctx/get", headers={**headers, **override}, json={"key": str(PUBLIC)}
                ) as response:
                    assert response.status == 403
                    assert "Access-Control-Allow-Origin" not in response.headers
            for path, body, status in (
                ("/ctx/get", {"key": str(PUBLIC)}, 200),
                ("/ctx/get", {"key": str(PRIVATE)}, 403),
                ("/ctx/set", {"key": str(PUBLIC), "value": "改写"}, 403),
                ("/not-open", {}, 404),
            ):
                async with client.post(url + path, headers=headers, json=body) as response:
                    assert response.status == status
                    assert response.headers["Access-Control-Allow-Origin"] == ORIGIN
                    assert TOKEN not in await response.text()
            assert ctx.get(PUBLIC) == "公开" and not active
            assert TOKEN not in str(ctx.snapshot())
        ctx.close()

    asyncio.run(scenario())


def test_websocket_authenticates_before_subscription_and_reconnects():
    async def scenario():
        registry, ctx, active, removed = make_host()
        policy = AccessPolicy(token=TOKEN, allowed_origins=(ORIGIN,))
        async with serve(registry, keys=[PUBLIC], port=0, access=policy) as url, ClientSession() as client:
            with pytest.raises(WSServerHandshakeError) as error:
                await client.ws_connect(url + "/ctx/watch", origin="https://evil.test")
            assert error.value.status == 403
            for token in (None, "wrong", 3):
                async with client.ws_connect(url + "/ctx/watch", origin=ORIGIN) as ws:
                    assert not active
                    ctx.set(PUBLIC, "认证前不可见")
                    await ws.send_json({"access_token": token, "key": str(PUBLIC)})
                    message = await ws.receive_json(timeout=2)
                    assert message["type"] == "error" and message["error"]["code"] == "unauthorized"
                    await ws.receive(timeout=2)
                    assert ws.close_code == 1008 and not active
            for _ in range(2):
                removed.clear()
                async with client.ws_connect(url + "/ctx/watch", origin=ORIGIN) as ws:
                    await ws.send_json({"access_token": TOKEN, "key": str(PUBLIC)})
                    assert await ws.receive_json(timeout=2) == {"type": "ready"}
                    assert len(active) == 1
                    ctx.set(PRIVATE, "不可见")
                    ctx.set(PUBLIC, "认证后可见")
                    assert (await ws.receive_json(timeout=2))["data"]["value"] == "认证后可见"
                await asyncio.wait_for(removed.wait(), 2)
                assert not active
            async with CtxClient(url, token=TOKEN) as native:
                assert await native.request("get", key=str(PUBLIC)) == "认证后可见"
                async with native.watch(key=str(PUBLIC)) as events:
                    ctx.set(PUBLIC, "Python 认证")
                    assert (await anext(events))["value"] == "Python 认证"
            async with CtxClient(url) as native:
                with pytest.raises(RemoteError, match="unauthorized"):
                    await native.request("list")
        assert not active
        ctx.close()

    asyncio.run(scenario())


def test_explicit_proxy_host_requires_token_even_without_origin():
    async def scenario():
        registry, ctx, _, _ = make_host()
        policy = AccessPolicy(
            token=TOKEN, allowed_hosts=("api.example.test",), allowed_origins=("https://panel.example.test",)
        )
        async with serve(registry, keys=[PUBLIC], port=0, access=policy) as url, ClientSession() as client:
            for headers, expected in (
                ({"Host": "api.example.test"}, 401),
                ({"Host": "api.example.test", "Authorization": f"Bearer {TOKEN}"}, 200),
                ({"X-Forwarded-Host": "api.example.test", "Authorization": f"Bearer {TOKEN}"}, 403),
            ):
                async with client.post(url + "/ctx/list", json={}, headers=headers) as response:
                    assert response.status == expected
        ctx.close()

    asyncio.run(scenario())

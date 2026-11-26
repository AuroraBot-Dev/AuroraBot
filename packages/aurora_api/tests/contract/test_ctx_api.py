"""验证 HTTP/WS 与进程内 ctx 的语义、暴露边界和订阅释放。"""

import asyncio
import json
from dataclasses import replace

import pytest
from aiohttp import ClientSession
from aurora_api.client import CtxClient, RemoteError
from aurora_api.protocol import SUBSCRIBE, UNSUBSCRIBE
from aurora_api.server import serve
from aurora_core.bootstrap import bootstrap
from aurora_core.ctx import StateKey, install_context
from aurora_core.ids import Id
from aurora_core.registry import RegistryEntry
from aurora_core.snapshots import JsonSnapshotStore

PUBLIC = Id("dev.api:state/public")
PRIVATE = Id("dev.api:state/private")


def make_host():
    registry = bootstrap()
    registry.register_many(RegistryEntry(key, "state_key", StateKey(), "test") for key in (PUBLIC, PRIVATE))
    ctx = install_context(registry)
    active = set()
    removed = asyncio.Event()

    def subscribe(callback, **filters):
        handle = ctx.subscribe(callback, **filters)
        active.add(handle)
        return handle

    def unsubscribe(handle):
        result = ctx.unsubscribe(handle)
        active.remove(handle)
        removed.set()
        return result

    registry.replace(replace(registry.get(SUBSCRIBE), target=subscribe))
    registry.replace(replace(registry.get(UNSUBSCRIBE), target=unsubscribe))
    return registry, ctx, active, removed


def test_http_roundtrip_matches_ctx_and_exact_locations():
    async def scenario():
        registry, ctx, _, _ = make_host()
        async with serve(registry, keys=[PUBLIC], port=0) as url, CtxClient(url) as client:
            assert await client.request("list") == []
            assert await client.request("set", key=str(PUBLIC), value=None) is None
            assert await client.request("get", key=str(PUBLIC)) is None
            where = {"scope": "中文"}
            value = {"text": "内容", "items": [1, None, True]}
            await client.request("set", key=str(PUBLIC), location=where, value=value)
            assert ctx.get(PUBLIC, location=where) == value
            assert await client.request("list", location={}) == [{"id": str(PUBLIC), "location": {}}]
            assert await client.request("list", key=str(PUBLIC), location=where) == [
                {"id": str(PUBLIC), "location": where}
            ]
            assert await client.request("delete", key=str(PUBLIC)) is True
            assert await client.request("delete", key=str(PUBLIC)) is False
            with pytest.raises(RemoteError, match="not_found"):
                await client.request("get", key=str(PUBLIC))
            assert ctx.get(PUBLIC, location=where) == value
        ctx.close()

    asyncio.run(scenario())


def test_watch_filters_orders_changes_and_releases_each_subscription():
    async def scenario():
        registry, ctx, active, removed = make_host()
        ctx.set(PUBLIC, "订阅前状态")
        async with serve(registry, keys=[PUBLIC], port=0) as url, CtxClient(url) as client:
            async with client.watch() as first, client.watch(key=str(PUBLIC), location={}) as second:
                assert len(active) == 2
                ctx.set(PRIVATE, "不可见")
                ctx.set(PUBLIC, 10, location={"scope": "other"})
                ctx.set(PUBLIC, 20)
                assert (await anext(first))["value"] == 10
                changed = await anext(first)
                assert changed == await anext(second)
                assert changed["previous"] == "订阅前状态"
                assert changed["existed"] is True
                assert changed["revision"] == 4
                ctx.delete(PUBLIC)
                deleted = await anext(first)
                assert deleted == await anext(second)
                assert deleted["action"] == "delete"
                assert deleted["value"] is None
                assert deleted["previous"] == 20
            async with asyncio.timeout(2):
                while active:
                    removed.clear()
                    if active:
                        await removed.wait()
            async with client.watch() as events:
                ctx.set(PUBLIC, "重新连接")
                assert (await anext(events))["value"] == "重新连接"
        assert not active
        ctx.close()

    asyncio.run(scenario())


def test_private_keys_are_hidden_from_every_action_and_error():
    async def scenario():
        registry, ctx, active, _ = make_host()
        secret = "private-token-must-not-appear"
        ctx.set(PRIVATE, secret)
        async with serve(registry, keys=[PUBLIC], port=0) as url, CtxClient(url) as client:
            assert await client.request("list") == []
            for action in ("get", "list", "set", "delete"):
                values = {"key": str(PRIVATE)}
                if action == "set":
                    values["value"] = "replacement"
                with pytest.raises(RemoteError, match="forbidden") as error:
                    await client.request(action, **values)
                assert secret not in str(error.value)
            with pytest.raises(RemoteError, match="forbidden"):
                async with client.watch(key=str(PRIVATE)):
                    pytest.fail("未开放的键不能订阅")
            assert not active
            assert ctx.get(PRIVATE) == secret
        ctx.close()

    asyncio.run(scenario())


def test_invalid_requests_and_browser_requests_do_not_mutate_state():
    async def scenario():
        registry, ctx, _, _ = make_host()
        async with serve(registry, keys=[PUBLIC], port=0) as url, ClientSession() as session:
            for content in (
                "[]",
                '{"key":null}',
                '{"key":"invalid"}',
                f'{{"key":"{PUBLIC}","value":NaN}}',
                f'{{"key":"{PUBLIC}","value":1,"value":2}}',
                f'{{"key":"{PUBLIC}","value":1,"location":{{"scope":2}}}}',
                f'{{"key":"{PUBLIC}","value":1,"extra":true}}',
            ):
                async with session.post(
                    url + "/ctx/set", data=content, headers={"Content-Type": "application/json"}
                ) as r:
                    assert r.status == 400
                    assert (await r.json())["error"]["code"] == "invalid_request"
            for headers in ({"Origin": "https://example.com"}, {"Host": "example.com"}):
                async with session.post(url + "/ctx/set", json={"key": str(PUBLIC), "value": 1}, headers=headers) as r:
                    assert r.status == 403
            async with session.post(url + "/ctx/set", data="{}") as r:
                assert r.status == 415
            async with session.post(url + "/operations/invoke", json={}) as r:
                assert r.status == 404
            assert ctx.list() == ()
        ctx.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("surrogate", [chr(0xD800), chr(0xDFFF)])
@pytest.mark.parametrize("field", ["value", "object_key", "location"])
def test_surrogates_are_rejected_before_commit_and_snapshot_remains_writable(tmp_path, surrogate, field):
    async def scenario():
        registry, ctx, _, _ = make_host()
        ctx.set(PUBLIC, "正常状态😀")
        before = ctx.snapshot()
        changes = []
        ctx.subscribe(changes.append)
        payload = {"key": str(PUBLIC), "value": surrogate}
        if field == "object_key":
            payload["value"] = {surrogate: "内容"}
        elif field == "location":
            payload["value"] = "内容"
            payload["location"] = {"scope": surrogate}
        async with (
            serve(registry, keys=[PUBLIC], port=0) as url,
            ClientSession() as session,
            session.post(
                url + "/ctx/set", data=json.dumps(payload), headers={"Content-Type": "application/json"}
            ) as response,
        ):
            assert response.status == 400
            assert (await response.json())["error"]["code"] == "invalid_request"
        assert ctx.snapshot() == before and changes == []
        store = JsonSnapshotStore(tmp_path / "ctx.json")
        store.save(ctx.snapshot())
        assert store.load() == before.records
        ctx.close()

    asyncio.run(scenario())


def test_validator_error_does_not_expose_private_details():
    async def scenario():
        registry, ctx, _, _ = make_host()

        def reject(value):
            raise ValueError("secret-validation-detail")

        registry.replace(replace(registry.get(PUBLIC), target=StateKey(reject)))
        async with serve(registry, keys=[PUBLIC], port=0) as url, CtxClient(url) as client:
            with pytest.raises(RemoteError, match="invalid_request") as error:
                await client.request("set", key=str(PUBLIC), value=1)
            assert "secret-validation-detail" not in str(error.value)
            assert ctx.list() == ()
        ctx.close()

    asyncio.run(scenario())


def test_slow_subscriber_is_disconnected_without_silently_dropping_changes():
    async def scenario():
        registry, ctx, active, removed = make_host()
        async with serve(registry, keys=[PUBLIC], port=0, queue_limit=1) as url, CtxClient(url) as client:
            async with client.watch() as events:
                ctx.set(PUBLIC, 1)
                ctx.set(PUBLIC, 2)
                with pytest.raises(RemoteError, match="slow_consumer"):
                    await anext(events)
            await asyncio.wait_for(removed.wait(), 2)
            assert not active
            assert await client.request("get", key=str(PUBLIC)) == 2
        ctx.close()

    asyncio.run(scenario())


def test_server_shutdown_closes_active_watch_before_ctx():
    async def scenario():
        registry, ctx, active, _ = make_host()
        server = serve(registry, keys=[PUBLIC], port=0)
        async with server as url, CtxClient(url) as client, client.watch() as events:
            assert active
            await asyncio.wait_for(server.__aexit__(None, None, None), 2)
            assert not active
            with pytest.raises(ConnectionError, match="订阅连接已关闭"):
                await anext(events)
            ctx.close()

    asyncio.run(scenario())


def test_read_only_keys_allow_observation_and_reject_all_writes():
    async def scenario():
        registry, ctx, _, _ = make_host()
        ctx.set(PUBLIC, "原值", location={"instance_id": "one"})
        async with serve(registry, keys=[PRIVATE], read_only_keys=[PUBLIC], port=0) as url, CtxClient(url) as client:
            assert await client.request("get", key=str(PUBLIC), location={"instance_id": "one"}) == "原值"
            assert await client.request("list", key=str(PUBLIC)) == [
                {"id": str(PUBLIC), "location": {"instance_id": "one"}}
            ]
            async with client.watch(key=str(PUBLIC)) as events:
                for location in ({}, {"instance_id": "one"}, {"instance_id": "two"}):
                    for action in ("set", "delete"):
                        with pytest.raises(RemoteError, match="forbidden"):
                            await client.request(
                                action,
                                key=str(PUBLIC),
                                location=location,
                                **({"value": "覆盖"} if action == "set" else {}),
                            )
                ctx.set(PUBLIC, "新值", location={"instance_id": "one"})
                assert (await anext(events))["value"] == "新值"
            await client.request("set", key=str(PRIVATE), value=1)
            assert await client.request("delete", key=str(PRIVATE)) is True
            assert ctx.get(PUBLIC, location={"instance_id": "one"}) == "新值"
        with pytest.raises(ValueError, match="同时声明"):
            async with serve(registry, keys=[PUBLIC], read_only_keys=[PUBLIC], port=0):
                pass
        ctx.close()

    asyncio.run(scenario())

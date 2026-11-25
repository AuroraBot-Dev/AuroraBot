"""验证公开描述与真实 HTTP/WS 载荷一致，以及生成产物可重复检查。"""

import asyncio
import subprocess
import sys
from pathlib import Path

import pytest
from aiohttp import ClientSession
from aurora_api.contract import describe_contract
from aurora_api.server import serve
from aurora_core.bootstrap import bootstrap
from aurora_core.ctx import StateKey, install_context
from aurora_core.ids import Id
from aurora_core.registry import RegistryEntry
from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[2]
PUBLIC = Id("dev.contract:state/public")
PRIVATE = Id("dev.contract:state/private")
FORMATS = FormatChecker()


@FORMATS.checks("aurora-id", raises=ValueError)
def valid_id(value):
    return not isinstance(value, str) or bool(Id(value))


def validator(name):
    contract = describe_contract()
    return Draft202012Validator(
        {"$schema": contract["$schema"], "$defs": contract["$defs"], "$ref": f"#/$defs/{name}"},
        format_checker=FORMATS,
    )


def test_descriptions_are_valid_isolated_and_have_only_transport_ids():
    contract = describe_contract()
    Draft202012Validator.check_schema(contract)
    bindings = contract["http"]
    assert set(bindings) == {"get", "list", "set", "delete"}
    for name, binding in bindings.items():
        assert binding["operation"] == f"org.aurora.core:operations/ctx/{name}"
    assert contract["watch"]["replay"] is False
    contract["$defs"]["GetRequest"]["properties"].clear()
    assert validator("GetRequest").is_valid({"key": str(PUBLIC)})


@pytest.mark.parametrize(
    ("name", "payload", "accepted"),
    [
        ("GetRequest", {"key": str(PUBLIC)}, True),
        ("GetRequest", {}, False),
        ("GetRequest", {"key": "invalid"}, False),
        ("WatchRequest", {"location": None}, False),
        ("SetRequest", {"key": str(PUBLIC), "value": None}, True),
        ("SetRequest", {"key": str(PUBLIC)}, False),
        ("SetRequest", {"key": str(PUBLIC), "value": 1, "extra": True}, False),
    ],
)
def test_request_descriptions_preserve_required_optional_and_null(name, payload, accepted):
    assert validator(name).is_valid(payload) is accepted


def test_live_http_and_websocket_match_exported_contract():
    async def scenario():
        registry = bootstrap()
        registry.register_many(RegistryEntry(key, "state_key", StateKey(), "test") for key in (PUBLIC, PRIVATE))
        ctx = install_context(registry)
        contract = describe_contract()

        async with serve(registry, keys=[PUBLIC], port=0, queue_limit=1) as url, ClientSession() as session:

            async def request(action, payload, status=200):
                binding = contract["http"][action]
                async with session.request(binding["method"], url + binding["path"], json=payload) as response:
                    assert response.status == status
                    body = await response.json()
                validator(f"{action.title()}Response" if status == 200 else "ErrorResponse").validate(body)
                return body

            async with session.ws_connect(url + contract["watch"]["path"]) as ws:
                await ws.send_json({})
                ready = await ws.receive_json(timeout=2)
                validator("WatchMessage").validate(ready)
                assert ready == {"type": "ready"}
                payload = {"key": str(PUBLIC), "value": {"中文": [None, True, 1.25, "😀"]}}
                assert await request("set", payload) == {"result": None}
                changed = await ws.receive_json(timeout=2)
                validator("WatchMessage").validate(changed)
                assert changed["data"]["existed"] is False
                assert changed["data"]["previous"] is None
                assert changed["data"]["value"] == payload["value"]
                assert (await request("get", {"key": str(PUBLIC)}))["result"] == payload["value"]
                assert (await request("list", {}))["result"] == [{"id": str(PUBLIC), "location": {}}]
                assert await request("delete", {"key": str(PUBLIC)}) == {"result": True}
                deleted = await ws.receive_json(timeout=2)
                validator("WatchMessage").validate(deleted)
                assert deleted["data"]["action"] == "delete"
                assert deleted["data"]["value"] is None
                assert await request("delete", {"key": str(PUBLIC)}) == {"result": False}
                await request("get", {"key": str(PUBLIC)}, 404)
                await request("get", {"key": str(PRIVATE)}, 403)
                await request("set", {"key": str(PUBLIC)}, 400)
                ctx.set(PUBLIC, 1)
                ctx.set(PUBLIC, 2)
                overflow = await ws.receive_json(timeout=2)
                validator("WatchMessage").validate(overflow)
                assert overflow["error"]["code"] == "slow_consumer"
            async with session.ws_connect(url + contract["watch"]["path"]) as ws:
                await ws.send_json({"key": str(PRIVATE)})
                refused = await ws.receive_json(timeout=2)
                validator("WatchMessage").validate(refused)
                assert refused["error"]["code"] == "forbidden"
        ctx.close()

    asyncio.run(scenario())


def test_generated_client_contract_matches_backend():
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/generate.py"), "--check"],
        cwd=ROOT,
        capture_output=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr

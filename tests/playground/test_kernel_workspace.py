from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from aurora_kernel import CLOSE, PREPARE, Context, namespace
from aurora_kernel.discovery import StaticSource
from playground.modules.kernel.environment import specification
from playground.protocol import Module
from playground.session import Session

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable


def call(session: Session, operation: str, **inputs: Any) -> dict[str, Any]:
    return session.handle(json.dumps({"module": "kernel", "operation": operation, "input": inputs}))


def test_kernel_selects_actual_modules_observes_routes_and_reuses_common_records() -> None:
    with Session() as session, Session() as other:
        call(session, "create", modules=["counter"])
        incremented = call(session, "increment", amount=3)["result"]
        assert incremented == {"value": 3}
        inspection = call(session, "inspect")["result"]
        assert inspection["modules"] == ["counter"]
        assert inspection["routes"][0]["handlers"] == ["counter"]
        assert call(session, "call", target="counter:changed", args=[3])["ok"]
        record = call(session, "export")["result"]
        assert record["version"] == "aurora.playground.record/v1"
        assert [item["operation"] for item in record["checkpoints"]] == ["increment", "call"]
        replay = call(other, "replay", archive=record)
        assert replay["ok"], replay
        assert replay["result"]["matched"]
        assert replay["result"]["state"]["namespaces"]["counter"]["history"] == [3]
        failed_reset = call(session, "reset", configuration={"modules": ["client"]})
        assert not failed_reset["ok"]
        assert call(session, "inspect")["result"]["modules"] == ["counter"]
        call(session, "reset", configuration={"modules": ["counter", "extension", "client"]})
        inspection = call(session, "inspect")["result"]
        route = next(item for item in inspection["routes"] if item["target"] == "counter:increment")
        assert route["handlers"] == ["extension"]
        assert call(session, "increment", amount=3)["result"] == {"value": 6}


def test_injected_namespace_uses_host_lifecycle_and_async_calls_without_agent_controls() -> None:
    events: list[str] = []

    @namespace("custom")
    def custom(ctx: Context) -> None:
        events.append("build")
        ctx["custom"]["value"] = 0

    @custom.on(PREPARE)
    async def prepare(_ctx: Context) -> Callable[[], Awaitable[None]]:
        events.append("prepare")

        async def release() -> None:
            events.append("release")

        return release

    @custom.on(CLOSE)
    def close(_ctx: Context) -> None:
        events.append("close")

    @custom.callpoint("add")
    async def add(ctx: Context, amount: int) -> int:
        ctx["custom"]["value"] += amount
        return ctx["custom"]["value"]

    module = Module("custom_kernel", "自定义 Kernel", workspace=specification((custom,)))
    with Session((StaticSource((module,)),)) as session:
        operations = session.handle('{"action":"describe","module":"custom_kernel"}')["result"]["operations"]
        names = {item["operation"] for item in operations}
        assert not names & {"step", "append", "cancel", "replay"}
        assert not events
        response = session.handle(
            json.dumps(
                {
                    "module": "custom_kernel",
                    "operation": "call",
                    "input": {"instance_id": "one", "target": "custom:add", "args": [4]},
                }
            )
        )
        assert response["result"] == {"value": 4}
        session.handle('{"module":"custom_kernel","operation":"create","input":{"instance_id":"two"}}')
        inspection = session.handle('{"module":"custom_kernel","operation":"inspect","input":{"instance_id":"one"}}')
        assert inspection["result"]["routes"][0]["asynchronous"]
        state = session.handle('{"module":"custom_kernel","operation":"state","input":{"instance_id":"two"}}')
        assert state["result"]["namespaces"]["custom"]["value"] == 0
        assert events == ["prepare", "build", "prepare", "build"]
    assert events == ["prepare", "build", "prepare", "build", "close", "release", "close", "release"]


def test_kernel_validates_module_selection_before_preparation() -> None:
    events: list[str] = []

    @namespace("selected")
    def selected(_ctx: Context) -> None:
        events.append("selected")

    @namespace("unused")
    def unused(_ctx: Context) -> None:
        events.append("unused")

    module = Module("selection", "模块选择", workspace=specification((selected, unused)))
    with Session((StaticSource((module,)),)) as session:
        duplicate = session.handle(
            '{"module":"selection","operation":"create","input":{"modules":["selected","selected"]}}'
        )
        assert duplicate["error"]["code"] == "invalid_input"
        assert session._runner is None
        missing = session.handle('{"module":"selection","operation":"create","input":{"modules":["absent"]}}')
        assert not missing["ok"]
        assert not events
        created = session.handle(
            '{"module":"selection","operation":"reset","input":{"configuration":{"modules":["selected"]}}}'
        )
        assert created["ok"]
        assert events == ["selected"]

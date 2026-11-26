"""在默认 bot 装配中验证环境周期、API 观察和恢复，不调用真实服务。"""

import asyncio
from dataclasses import replace
from functools import partial
from typing import cast

import httpx
import tomli_w
from aurora_api.client import CtxClient
from aurora_api.server import serve
from aurora_core import entry_from
from aurora_core.discovery import load_plugins
from aurora_core.snapshots import JsonSnapshotStore
from aurora_world import ENVIRONMENT, SOURCE_STATUS, SourceSpec
from aurora_world.environment import TIME, WEATHER, create_time, create_weather
from test_default_assembly import seed, setup

LOCATION = {"place": "南京", "latitude": 32.0617, "longitude": 118.7778}


class Period:
    def __init__(self):
        self.waiting = asyncio.Queue()
        self.wake = asyncio.Queue()

    async def sleep(self, seconds):
        self.waiting.put_nowait(seconds)
        await self.wake.get()


def weather_response(request):
    return httpx.Response(
        200,
        json={
            "current": {"time": 1793606400, "temperature_2m": 18.5, "weather_code": 2, "wind_speed_10m": 6.2},
            "current_units": {"temperature_2m": "°C", "wind_speed_10m": "km/h"},
        },
    )


def test_default_assembly_exposes_environment_without_activating_model_and_restores(tmp_path):
    async def scenario():
        path = tmp_path / "config/org.aurora.world/config.toml"
        path.parent.mkdir(parents=True)
        path.write_text(
            tomli_w.dumps(
                {
                    "sources": [
                        {"source": str(TIME), "source_id": "environment/time", "config": {"mean_seconds": 1800}},
                        {"source": str(WEATHER), "source_id": "environment/weather", "config": LOCATION},
                    ]
                }
            ),
            encoding="utf-8",
        )
        previous = ()
        for restart in (False, True):
            clocks = [Period(), Period()]
            plugins = load_plugins(
                enabled=[
                    "aurora_world",
                    "aurora_world.configuration",
                    "aurora_world.environment",
                    "aurora_config",
                ]
            )
            host, assembly, ctx, registry, clients, _, _, _ = setup(
                tmp_path, extra_plugins=[plugin for plugin in plugins if plugin.name != "aurora_config"]
            )
            for identity, factory in (
                (TIME, partial(create_time, sleep=clocks[0].sleep, uniform=lambda a, b: 0.5)),
                (
                    WEATHER,
                    partial(
                        create_weather,
                        sleep=clocks[1].sleep,
                        transport=httpx.MockTransport(weather_response),
                    ),
                ),
            ):
                registry.replace(replace(registry.get(identity), target=SourceSpec(factory)))
            registry.register_many(
                entry_from(target, provider="test")
                for target in (
                    ctx.get,
                    ctx.set,
                    ctx.delete,
                    ctx.list,
                    ctx.subscribe,
                    ctx.unsubscribe,
                )
            )
            await host.start(configure=partial(seed, ctx, tools=False))
            try:
                assert await clocks[0].waiting.get() == (2100 if restart else 1800)
                assert await clocks[1].waiting.get() == 900
                assert assembly.world_records is not None
                records = assembly.world_records.observations()
                previous_weather = tuple(record for record in previous if record.source_id == "environment/weather")
                assert records[: len(previous_weather)] == previous_weather
                assert len(records) == len(previous_weather) + 2
                if previous:
                    assert records[-1].position.sequence == previous_weather[-1].position.sequence + 1
                assert len({record.message_id for record in records}) == len(records)
                assert clients[0].requests == []
                async with serve(registry, keys=[ENVIRONMENT, SOURCE_STATUS], port=0) as url, CtxClient(url) as client:
                    value = cast(
                        dict,
                        await client.request(
                            "get", key=str(ENVIRONMENT), location={"source_id": "environment/weather"}
                        ),
                    )
                    assert value["records"][-1]["payload"]["place"] == "南京"
                    state = cast(
                        dict,
                        await client.request(
                            "get", key=str(SOURCE_STATUS), location={"source_id": "environment/weather"}
                        ),
                    )
                    assert state["status"] == "running" and state["accepting"] is True
                    async with client.watch(
                        key=str(ENVIRONMENT), location={"source_id": "environment/time"}
                    ) as changes:
                        clocks[0].wake.put_nowait(None)
                        assert await clocks[0].waiting.get() == (2100 if restart else 1800)
                        change = await asyncio.wait_for(anext(changes), timeout=2)
                        assert change["value"]["records"][-1]["payload"]["kind"] == "time"
                    value = cast(
                        dict,
                        await client.request("get", key=str(ENVIRONMENT), location={"source_id": "environment/time"}),
                    )
                    assert len(value["records"]) == 1
                    assert (
                        value["records"][-1]["sequence"]
                        == next(item for item in records if item.source_id == "environment/time").position.sequence + 1
                    )
                assert clients[0].requests == []
                result = await assembly.runtime.submit("显式交流").run.wait()
                assert result.status == "completed" and clients[0].requests
                previous = assembly.world_records.observations()
            finally:
                await host.stop()
            snapshot = JsonSnapshotStore(tmp_path / "framework/ctx.json").load()
            assert all(item.address.key != SOURCE_STATUS for item in snapshot)
            stored = [item.value for item in snapshot if item.address.key == ENVIRONMENT]
            assert sum(len(cast(dict, value)["records"]) for value in stored) == len(previous)
            if not restart:
                text = path.read_text(encoding="utf-8")
                path.write_text(text.replace("mean_seconds = 1800", "mean_seconds = 2100"), encoding="utf-8")

    asyncio.run(scenario())

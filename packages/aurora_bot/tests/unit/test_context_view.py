"""验证模型业务视图的来源、预算、过期刷新及读取边界。"""

import json

import pytest
from aurora_bot.assembly_config import parse_config
from aurora_bot.context_view import BusinessContextView
from aurora_control import ExecutionRequest
from aurora_core import Id
from aurora_core.bootstrap import bootstrap
from aurora_core.ctx import Context, StateKey
from aurora_core.discovery import register_plugins
from aurora_core.registry import RegistryEntry
from aurora_world import ENVIRONMENT, WorldRecords
from aurora_world.plugin import plugin


@pytest.fixture
def world():
    registry = bootstrap()
    register_plugins(registry, [plugin()])
    hidden = Id("dev.view:state/private")
    registry.register(RegistryEntry(hidden, "state_key", StateKey(), "test"))
    ctx = Context(registry)
    ctx.set(hidden, {"credential": "never-expose", "model_input": "previous-prompt"})
    clock = [10000.0]
    records = WorldRecords(ctx, now=lambda: clock[0])
    records.select("clock", "time")
    records.select("weather", "weather")
    records.open()
    try:
        yield ctx, records, clock
    finally:
        records.close()
        ctx.close()


def render(records, **options):
    config = parse_config({"instance_id": "main", "model_role": "reasoning", "context_view": options})
    return BusinessContextView(records, config["context_view"])(ExecutionRequest("view"))


def test_view_preserves_source_references_and_observation_types(world):
    _, records, _ = world
    event = records.append(source_id="chat", message_id="message-1", payload="设备告警").record
    weather = records.append(source_id="weather", message_id="sample-1", payload={"temperature": 18}).record
    text = render(records)
    view = json.loads(text)
    assert view["kind"] == "business_context"
    assert "never-expose" not in text and "previous-prompt" not in text
    item = view["events"]["records"][0]
    assert (item["source_id"], item["message_id"], item["received_at"]) == ("chat", "message-1", 10000)
    assert (item["record_id"], item["journal_id"]) == (event.record_id, event.position.journal_id)
    assert item["text"] == "设备告警" and not item["abridged"]
    item = view["environment"]["records"][0]
    assert item["record_id"] == weather.record_id and item["kind"] == "weather"
    assert json.loads(item["text"]) == {"temperature": 18}
    assert view["events"]["omitted"] == view["environment"]["omitted"] == 0


@pytest.mark.parametrize("budget", [1024, 1600, 2500, 12000])
def test_budget_includes_metadata_and_preserves_archive_and_deduplication(world, budget):
    ctx, records, _ = world
    payload = '告警"\\\n' * 1800
    events = [records.append(source_id="chat", message_id=str(i), payload=payload).record for i in range(8)]
    records.append(source_id="weather", message_id="sample", payload={"description": payload})
    before = ctx.snapshot()
    text = render(records, max_chars=budget)
    view = json.loads(text)
    assert len(text) <= budget and ctx.snapshot() == before
    for name in ("events", "environment"):
        section = view[name]
        assert section["omitted"] >= 0
        assert all(item["abridged"] for item in section["records"])
    if view["events"]["records"]:
        latest = view["events"]["records"][-1]
        assert latest["record_id"] == events[-1].record_id
        assert records.get_by_id(latest["record_id"]).payload == payload
    assert records.read() == tuple(events)
    assert records.append(source_id="chat", message_id="0", payload=payload).duplicate


def test_expired_observations_refresh_before_inference_without_pruning_archive(world):
    ctx, records, clock = world
    event = records.append(source_id="chat", message_id="old", payload="旧事件").record
    records.append(source_id="clock", message_id="tick", payload={"time": "当前时间"})
    records.append(source_id="weather", message_id="sample", payload={"temperature": 18})
    clock[0] += 3601
    view = json.loads(render(records))
    assert view["events"]["records"] == []
    assert [item["kind"] for item in view["environment"]["records"]] == ["time", "weather"]
    weather = ctx.get(ENVIRONMENT, location={"source_id": "weather"})["records"]
    assert len(weather) == 1 and weather[0]["payload"] == {"temperature": 18}
    assert weather[0]["received_at"] < clock[0] - 3600
    assert records.get_by_id(event.record_id).payload == "旧事件"


def test_disabled_sections_and_oversized_identity_are_explicit(world):
    _, records, _ = world
    records.append(source_id="s" * 3000, message_id="large-id", payload="保留完整身份")
    records.append(source_id="weather", message_id="sample", payload={"temperature": 18})
    view = json.loads(render(records, max_chars=1024, environment=False))
    assert view["events"]["records"] == [] and view["events"]["omitted"] == 1
    assert view["environment"] == {"enabled": False, "records": [], "omitted": 0}
    view = json.loads(render(records, events=False))
    assert view["events"] == {"enabled": False, "records": [], "omitted": 0}
    assert view["environment"]["records"]
    assert render(records, enabled=False) == render(records, events=False, environment=False) == ""

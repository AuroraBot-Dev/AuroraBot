"""通过真实宿主和可控时钟验收持续决策、引导去重及关闭恢复。"""

import asyncio
import json
import random
from copy import deepcopy
from dataclasses import asdict
from typing import cast

import pytest
import tomli_w
from aurora_adapter.model.config import ADAPTERS, BINDINGS, ModelAdapter
from aurora_adapter.model.config import CONFIG as MODEL_CONFIG
from aurora_agent.react import AgentBusyError
from aurora_bot.assembly_config import CONFIG
from aurora_bot.cadence import plugin as cadence_plugin
from aurora_bot.cadence.state import CHECKPOINT, CONFIG_STATE
from aurora_bot.cadence.timing import CadenceTiming
from aurora_bot.work_notes import WorkNotes
from aurora_control import ExecutionRequest
from aurora_core import Id
from aurora_core.json_data import encode_json
from aurora_core.registry import RegistryEntry
from aurora_core.snapshots import JsonSnapshotStore
from aurora_world.plugin import plugin as world_plugin
from test_cadence import append, state, until
from test_default_assembly import seed, setup


class Clock:
    def __init__(self):
        self.now = 1000.0
        self.waits = asyncio.Queue()
        self.delays = []
        self.timing = CadenceTiming(lambda: self.now, self.sleep, random.Random(7).uniform, lambda: self.now)

    async def sleep(self, delay):
        gate = asyncio.get_running_loop().create_future()
        self.delays.append(delay)
        self.waits.put_nowait((delay, gate))
        await gate

    async def tick(self):
        async with asyncio.timeout(3):
            while True:
                delay, gate = await self.waits.get()
                if not gate.done():
                    break
        self.now += delay
        gate.set_result(None)
        return len(self.delays)


class Decisions:
    def __init__(self):
        self.choice = "observe"
        self.requests = []
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.hold = False
        self.closed = False
        self.cleaned = False

    async def choose(self, request):
        self.requests.append(deepcopy(request))
        self.entered.set()
        try:
            if self.hold:
                await self.release.wait()
            return self.choice
        finally:
            self.cleaned = True

    async def aclose(self):
        assert not self.hold or self.cleaned
        self.closed = True


def configured(root, *, decision_config=None):
    clock, decisions = Clock(), Decisions()
    path = root / "config/org.aurora.bot/cadence.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(
            tomli_w.dumps(
                {
                    "decision": {
                        "model_role": "cadence",
                        "active_seconds": 5,
                        "idle_seconds": 60,
                        **(decision_config or {}),
                    },
                }
            ),
            encoding="utf-8",
        )
    host, assembly, ctx, registry, clients, _, events, _ = setup(
        root, extra_plugins=(world_plugin(), cadence_plugin()), assembly_options={"cadence_timing": clock.timing}
    )

    async def factory(config, *, api_key=None):
        events.append("decision.created")
        return decisions

    adapter = Id("dev.cadence:adapters/choice")
    registry.register(RegistryEntry(adapter, "adapter", ModelAdapter("choice", factory), "test", register_to=ADAPTERS))

    def configure():
        seed(ctx, tools=False)
        ctx.set(CONFIG, {**cast(dict, ctx.get(CONFIG)), "notes": {"enabled": True}})
        ctx.set(
            MODEL_CONFIG, {**cast(dict, ctx.get(MODEL_CONFIG)), "decision": {"adapter": str(adapter), "model": "fake"}}
        )
        ctx.set(BINDINGS, {**cast(dict, ctx.get(BINDINGS)), "cadence": "decision"})

    return host, assembly, ctx, clients, clock, decisions, configure, events


async def tick(clock, ctx):
    previous = state(ctx)["observation"]
    waits = await clock.tick()
    await until(
        lambda: state(ctx)["observation"] != previous or state(ctx)["error"] is not None or len(clock.delays) > waits
    )


def note(ctx, identity="main", *, expected_revision=0, text="核对未完成事项"):
    return WorkNotes(ctx, identity).write(
        {
            "note_id": "task",
            "expected_revision": expected_revision,
            "text": text,
            "status": "active",
            "references": [],
        },
        ExecutionRequest("write-note"),
        "note-call",
    )


def test_observe_deduplicates_material_but_rechecks_after_idle_and_on_changes(tmp_path):
    async def scenario():
        host, assembly, ctx, clients, clock, decisions, configure, _ = configured(tmp_path)
        await host.start(configure=configure)
        try:
            first = append(assembly)
            other = append(assembly, "other-source", source="other", payload="其他来源也参与决策")
            note(ctx, "other", text="不应暴露的其他实例笔记")
            for _ in range(3):
                await tick(clock, ctx)
                assert state(ctx)["position"] == asdict(other.record.position)
                assert state(ctx)["event_position"] is None and state(ctx)["receipts"] == []
                records = decisions.requests[-1]["state"]["business"]["events"]["records"]
                assert [record["record_id"] for record in records] == [first.record.record_id, other.record.record_id]
                assert "不应暴露" not in encode_json(decisions.requests[-1])
            assert clients[0].requests == []
            assert len(decisions.requests) == 1
            assert all(5 <= delay <= 72 for delay in clock.delays)
            assert len(set(clock.delays)) > 1
            note(ctx)
            await tick(clock, ctx)
            assert len(decisions.requests) == 2
            decisions.choice = "attend_events"
            clock.now += 60
            await tick(clock, ctx)
            assert len(state(ctx)["receipts"]) == 1
            assert state(ctx)["event_position"] == asdict(other.record.position)
            await until(lambda: assembly.runtime.current is None)
            assert clients[0].requests
            guidance = next(
                json.loads(message["content"])
                for message in clients[0].requests[-1]["messages"]
                if message["role"] == "user" and json.loads(message["content"]).get("kind") == "cadence_decision"
            )
            assert set(guidance["business"]) == {"events", "environment"}
            clock.now += 200
            await tick(clock, ctx)
            assert len(state(ctx)["receipts"]) == 1
            assert state(ctx)["observation"]["disposition"] == "no_material"
        finally:
            await host.stop()
        assert decisions.closed

    asyncio.run(scenario())


@pytest.mark.parametrize("stimulus", ["note", "event"])
def test_context_activity_interrupts_idle_wait_and_feedback_eventually_settles(tmp_path, stimulus):
    async def scenario():
        host, assembly, ctx, _, clock, decisions, configure, _ = configured(tmp_path)
        await host.start(configure=configure)
        try:
            for _ in range(35):
                await tick(clock, ctx)
            await until(lambda: not clock.waits.empty())
            assert clock.delays[-1] >= 48
            count = len(clock.delays)
            unchanged = state(ctx)
            ctx.set(CHECKPOINT, unchanged, location={"instance_id": "main"})
            for _ in range(5):
                await asyncio.sleep(0)
            assert len(clock.delays) == count
            if stimulus == "note":
                note(ctx)
            else:
                append(assembly, payload="普通文本消息")
            await until(lambda: len(clock.delays) > count)
            assert 5 <= clock.delays[-1] <= 17
            await tick(clock, ctx)
            assert decisions.requests[-1]["state"]["business"]["notes" if stimulus == "note" else "events"]["records"]
            assert state(ctx)["error"] is None and state(ctx)["receipts"] == []
            records = assembly.world_records
            assert records is not None
            records.select("environment/time", "time")
            decisions.choice = "attend_events"
            records.append(source_id="environment/time", message_id="passive", payload={"trigger": "context"})
            count = len(decisions.requests)
            await tick(clock, ctx)
            assert len(decisions.requests) == count
            clock.now += 60
            await tick(clock, ctx)
            assert any(item["kind"] == "world_environment" for item in state(ctx)["receipts"][-1]["references"])
        finally:
            await host.stop()

    asyncio.run(scenario())


@pytest.mark.parametrize("with_events", [False, True])
def test_selected_environment_sources_enter_decisions_without_becoming_archived_events(tmp_path, with_events):
    async def scenario():
        host, assembly, ctx, clients, clock, decisions, configure, _ = configured(tmp_path)
        records = assembly.world_records
        assert records is not None
        records.select("environment/time", "time")
        records.select("environment/weather", "weather")
        await host.start(configure=configure)
        try:
            records.append(source_id="environment/time", message_id="time-1", payload="当前时间")
            records.append(source_id="environment/weather", message_id="weather-1", payload="南京天气")
            event = append(assembly) if with_events else None
            await tick(clock, ctx)
            business = decisions.requests[-1]["state"]["business"]
            assert {item["source_id"] for item in business["environment"]["records"]} == {
                "environment/time",
                "environment/weather",
            }
            assert len(business["events"]["records"]) == int(with_events)
            assert len(records.read()) == int(with_events)
            assert state(ctx)["error"] is None and state(ctx)["receipts"] == []
            assert clients[0].requests == []
            decisions.choice = "attend_events"
            clock.now += 60
            await tick(clock, ctx)
            if event is not None:
                assert state(ctx)["event_position"] == asdict(event.record.position)
                assert len(state(ctx)["receipts"]) == 1
                await until(lambda: assembly.runtime.current is None)
            else:
                assert state(ctx)["observation"]["disposition"] == "submitted"
                assert state(ctx)["event_position"] is None and len(state(ctx)["receipts"]) == 1
                await until(lambda: assembly.runtime.current is None)
            assert set(state(ctx)["environment_positions"]) == {"environment/time", "environment/weather"}
            clock.now += 200
            await tick(clock, ctx)
            assert len(state(ctx)["receipts"]) == 1
            assert state(ctx)["observation"]["disposition"] == "no_material"
            assert records.presentation("environment/time") == "time"
            assert records.presentation("environment/weather") == "weather"
        finally:
            await host.stop()
        assert decisions.closed and clients[0].closed

    asyncio.run(scenario())


def test_no_event_ticks_review_notes_and_preserve_receipts_across_restart(tmp_path):
    async def scenario():
        for restart in (False, True):
            host, assembly, ctx, clients, clock, decisions, configure, _ = configured(tmp_path)
            decisions.choice = "review_work"
            await host.start(configure=configure)
            try:
                if not restart:
                    note(ctx)
                    await tick(clock, ctx)
                    assert len(state(ctx)["receipts"]) == 1
                    await until(lambda assembly=assembly: assembly.runtime.current is None)
                    decisions.choice = "observe"
                    await tick(clock, ctx)
                    assert len(decisions.requests) == 1
                    assert state(ctx)["observation"]["disposition"] == "submitted"
                    clock.now += 60
                    await tick(clock, ctx)
                    assert len(state(ctx)["receipts"]) == 1
                    assert state(ctx)["observation"]["disposition"] == "observed"
                else:
                    assert clients[0].requests == [] and len(state(ctx)["receipts"]) == 1
                    await tick(clock, ctx)
                    assert len(state(ctx)["receipts"]) == 2
                    assert state(ctx)["event_position"] is None
                    await until(lambda assembly=assembly: assembly.runtime.current is None)
                    assert clients[0].requests
            finally:
                await host.stop()
            assert decisions.closed
        snapshot = JsonSnapshotStore(tmp_path / "framework/ctx.json").load()
        assert any(item.address.key == CHECKPOINT for item in snapshot)
        assert all(item.address.key != CONFIG_STATE for item in snapshot)

    asyncio.run(scenario())


@pytest.mark.parametrize("fault", ["before_submit", "after_submit", "commit"])
def test_uncertain_decision_delivery_pauses_across_restart(tmp_path, monkeypatch, fault):
    async def scenario():
        host, assembly, ctx, _, clock, decisions, configure, _ = configured(tmp_path)
        decisions.choice = "attend_events"
        await host.start(configure=configure)
        append(assembly)
        submit, save = assembly.runtime.submit, ctx.set
        calls = []

        def broken_submit(payload):
            calls.append(payload)
            if fault == "after_submit":
                submit(payload)
            raise RuntimeError("投递结果未知")

        def broken_save(key, value, **kwargs):
            if key == CHECKPOINT and value["receipts"]:
                raise OSError("回执写入失败")
            save(key, value, **kwargs)

        if fault == "commit":
            monkeypatch.setattr(ctx, "set", broken_save)
        else:
            monkeypatch.setattr(assembly.runtime, "submit", broken_submit)
        try:
            await tick(clock, ctx)
            assert state(ctx)["error"] == "TransferUncertain"
            assert state(ctx)["pending"] is not None
            assert state(ctx)["receipts"] == [] and state(ctx)["event_position"] is None
            assert len(decisions.requests) == 1
            saved = state(ctx)
        finally:
            monkeypatch.setattr(ctx, "set", save)
            await host.stop()
        restarted, _, other_ctx, clients, _, other_decisions, other_configure, events = configured(tmp_path)
        await restarted.start(configure=other_configure)
        try:
            assert state(other_ctx) == saved
            assert other_decisions.requests == [] and clients[0].requests == []
            assert "decision.created" not in events
        finally:
            await restarted.stop()

    asyncio.run(scenario())


def test_shutdown_cancels_decision_before_closing_client_and_does_not_submit(tmp_path):
    async def scenario():
        host, assembly, _, clients, clock, decisions, configure, _ = configured(tmp_path)
        decisions.hold = True
        decisions.choice = "attend_events"
        await host.start(configure=configure)
        append(assembly)
        await clock.tick()
        await decisions.entered.wait()
        await host.stop()
        assert decisions.cleaned and decisions.closed
        snapshot = JsonSnapshotStore(tmp_path / "framework/ctx.json").load()
        saved = cast(dict, next(item.value for item in snapshot if item.address.key == CHECKPOINT))
        assert saved["pending"] is None and saved["observation"] is None
        assert clients[0].requests == []

    asyncio.run(scenario())


@pytest.mark.parametrize("fault", ["timeout", "invalid_choice"])
def test_decision_failure_pauses_without_fallback_action(tmp_path, fault):
    async def scenario():
        host, assembly, ctx, clients, clock, decisions, configure, _ = configured(
            tmp_path, decision_config={"timeout_seconds": 0.03}
        )
        decisions.hold = fault == "timeout"
        decisions.choice = "invalid"
        await host.start(configure=configure)
        try:
            append(assembly)
            await tick(clock, ctx)
            assert state(ctx)["error"] == "DecisionFailed"
            assert state(ctx)["receipts"] == [] and state(ctx)["pending"] is None
            assert clients[0].requests == [] and decisions.cleaned
        finally:
            await host.stop()

    asyncio.run(scenario())


def test_decision_can_feed_the_existing_busy_run_and_direct_conversation(tmp_path):
    async def scenario():
        host, assembly, ctx, _, clock, decisions, configure, _ = configured(tmp_path)
        decisions.choice = "attend_events"
        await host.start(configure=configure)
        release, entered = asyncio.Event(), asyncio.Event()
        activate = assembly.runtime._activate

        async def held(request):
            entered.set()
            await release.wait()
            await activate(request)

        assembly.runtime._activate = held
        try:
            direct = assembly.runtime.submit("直接交流")
            await entered.wait()
            append(assembly)
            await tick(clock, ctx)
            assert decisions.requests[-1]["state"]["bot"]["busy"]
            assert state(ctx)["receipts"][0]["run_id"] == direct.run.run_id
            assert assembly.agent is not None
            payloads = [item["payload"] for item in assembly.agent.pending(ExecutionRequest("inspect"))]
            assert payloads[0] == "直接交流"
            assert isinstance(payloads[1], dict) and payloads[1]["kind"] == "cadence_decision"
            release.set()
            assert (await direct.run.wait()).status == "completed"
        finally:
            release.set()
            await host.stop()

    asyncio.run(scenario())


def test_budget_and_source_selection_apply_before_decision(tmp_path):
    async def scenario():
        host, assembly, ctx, _, clock, decisions, configure, _ = configured(
            tmp_path, decision_config={"max_chars": 4096}
        )
        await host.start(configure=configure)
        try:
            append(assembly, payload='中文"\\\n' * 10000)
            note(ctx, text="工作" * 7000)
            await tick(clock, ctx)
            assert state(ctx)["error"] is None
            assert len(encode_json(decisions.requests[0])) <= 4096
            business = decisions.requests[0]["state"]["business"]
            assert business["notes"]["records"][0]["abridged"]
            assert "runtime-secret" not in encode_json(decisions.requests[0])
        finally:
            await host.stop()

    asyncio.run(scenario())


def test_mode_change_requires_explicit_handling_of_existing_snapshot(tmp_path):
    async def scenario():
        from test_cadence import configured as forward_configured

        host, assembly, ctx, *_ = forward_configured(tmp_path)
        await host.start(configure=lambda: seed(ctx, tools=False))
        append(assembly)
        await until(lambda: bool(state(ctx)["receipts"]))
        await host.stop()
        path = tmp_path / "config/org.aurora.bot/cadence.toml"
        path.write_text('[decision]\nmodel_role = "cadence"\n', encoding="utf-8")
        snapshot = (tmp_path / "framework/ctx.json").read_bytes()
        restarted, _, _, _, _, _, configure, events = configured(tmp_path)
        with pytest.raises(ValueError, match="模式与已有快照不一致"):
            await restarted.start(configure=configure)
        assert "decision.created" not in events
        assert (tmp_path / "framework/ctx.json").read_bytes() == snapshot

    asyncio.run(scenario())


def test_explicit_busy_rejection_leaves_event_for_the_next_decision(tmp_path, monkeypatch):
    async def scenario():
        host, assembly, ctx, _, clock, decisions, configure, _ = configured(tmp_path)
        decisions.choice = "attend_events"
        await host.start(configure=configure)
        original = assembly.runtime.submit

        def reject(payload):
            raise AgentBusyError("正在取消收尾，尚未写入引导")

        try:
            append(assembly)
            monkeypatch.setattr(assembly.runtime, "submit", reject)
            await tick(clock, ctx)
            assert state(ctx)["observation"]["disposition"] == "busy"
            assert state(ctx)["pending"] is None and state(ctx)["event_position"] is None
            monkeypatch.setattr(assembly.runtime, "submit", original)
            await tick(clock, ctx)
            assert len(state(ctx)["receipts"]) == 1 and state(ctx)["error"] is None
            await until(lambda: assembly.runtime.current is None)
        finally:
            await host.stop()

    asyncio.run(scenario())


def test_receipt_window_does_not_roll_back_event_deduplication(tmp_path):
    async def scenario():
        host, assembly, ctx, _, clock, decisions, configure, _ = configured(tmp_path)
        decisions.choice = "attend_events"
        await host.start(configure=configure)
        try:
            for index in range(65):
                event = append(assembly, str(index))
                clock.now += 100
                await tick(clock, ctx)
                await until(lambda: assembly.runtime.current is None)
                assert state(ctx)["event_position"] == asdict(event.record.position)
            assert len(state(ctx)["receipts"]) == 64
            assert state(ctx)["receipts"][-1]["references"] == [
                {
                    "kind": "world_event",
                    "journal_id": event.record.position.journal_id,
                    "record_id": event.record.record_id,
                }
            ]
            clock.now += 200
            await tick(clock, ctx)
            assert state(ctx)["observation"]["disposition"] == "no_material"
            assert len(state(ctx)["receipts"]) == 64
        finally:
            await host.stop()

    asyncio.run(scenario())

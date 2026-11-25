"""验证来源声明接入、身份绑定和接纳入口的启停约束。"""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest
from aurora_core import Id
from aurora_core.admission import AdmissionStatus, inspect_admissions
from aurora_core.bootstrap import bootstrap
from aurora_core.ctx import Context
from aurora_core.discovery import register_plugins
from aurora_core.hooks import HookConnections
from aurora_core.lifecycle import CLEAN, PREPARE, START, STOP, Lifecycle, install_lifecycle_slots
from aurora_core.registry import RegistryEntry
from aurora_world import (
    SOURCE_STATUS,
    SOURCES,
    MessageConflictError,
    SourceInstance,
    SourceSpec,
    SourceUnavailableError,
    WorldRecords,
    WorldSources,
)
from aurora_world.plugin import plugin

SOURCE = Id("dev.sources:sources/manual")


@pytest.fixture
def environment():
    registry = bootstrap()
    install_lifecycle_slots(registry)
    register_plugins(registry, [plugin()])
    ctx, hooks = Context(registry), HookConnections(registry)
    captures, events = {}, []

    async def factory(*, source_id, emit, config):
        captures[source_id] = emit, config
        events.append((source_id, "prepare"))
        with pytest.raises(SourceUnavailableError):
            emit(message_id="early", payload=None)

        async def start():
            events.append((source_id, "start"))

        async def stop():
            with pytest.raises(SourceUnavailableError):
                emit(message_id="late", payload=None)
            events.append((source_id, "stop"))

        async def close():
            events.append((source_id, "close"))

        return SourceInstance(start, stop, close)

    registry.register(RegistryEntry(SOURCE, "source", SourceSpec(factory), "test", register_to=SOURCES))
    records = WorldRecords(ctx)
    records.open()
    sources = WorldSources(ctx, hooks, records)
    yield registry, ctx, hooks, sources, captures, events
    records.close()
    hooks.close()
    ctx.close()


def test_source_admission_and_component_binding_do_not_run_factories(environment):
    registry, ctx, hooks, sources, captures, events = environment
    admissions = inspect_admissions(registry)
    assert all(item.status == AdmissionStatus.ACCEPTED for item in admissions)
    assert next(item for item in admissions if item.source == SOURCE).target == SOURCES
    sources.add(SOURCE, source_id="sensor/a")
    component = sources.component(depends_on=("shared-client",))
    assert component.depends_on == ("shared-client",)
    for phase in (PREPARE, START, STOP, CLEAN):
        assert len(hooks.for_slot(phase, component.instance_id)) == 1
    assert events == [] and captures == {} and ctx.list() == ()


def test_same_definition_has_independent_bound_identities_and_config_copies(environment):
    _, ctx, hooks, sources, captures, events = environment
    config = {"nested": ["原配置"]}
    sources.add(SOURCE, source_id="sensor/a", config=config)
    sources.add(SOURCE, source_id="sensor/b", config=config)
    config["nested"].clear()

    async def scenario():
        host = Lifecycle(ctx, hooks, [sources.component()])
        await host.start()
        a, first_config = captures["sensor/a"]
        b, second_config = captures["sensor/b"]
        first_config["nested"].clear()
        assert second_config == {"nested": ["原配置"]}
        try:
            first = a(message_id="1", payload="原文")
            second = b(message_id="1", payload="原文")
            assert first.record.source_id == "sensor/a" and second.record.source_id == "sensor/b"
            assert first.record.record_id != second.record.record_id
            assert a(message_id="1", payload="原文").duplicate
            with pytest.raises(MessageConflictError):
                a(message_id="1", payload="变化")
            with pytest.raises(TypeError):
                a(source_id="sensor/b", message_id="2", payload="不能冒用")
            with ThreadPoolExecutor(max_workers=1) as executor, pytest.raises(RuntimeError, match="线程"):
                executor.submit(a, message_id="thread", payload=None).result()
            assert len(sources.records.read()) == 2
            sources.stop_accepting()
            sources.stop_accepting()
            for emit in (a, b):
                with pytest.raises(SourceUnavailableError):
                    emit(message_id="1", payload="原文")
            assert len(sources.records.read()) == 2
        finally:
            await host.stop()
        for emit in (a, b):
            with pytest.raises(SourceUnavailableError):
                emit(message_id="after-close", payload=None)
        assert events[-4:] == [("sensor/b", "stop"), ("sensor/a", "stop"), ("sensor/b", "close"), ("sensor/a", "close")]

    asyncio.run(scenario())


def test_before_start_and_after_stop_callbacks_cannot_reopen(environment):
    _, ctx, _, sources, captures, _ = environment
    sources.add(SOURCE, source_id="sensor/a")

    async def scenario():
        with pytest.raises(RuntimeError, match="尚未准备"):
            await sources.start()
        await sources.prepare()
        emit, _ = captures["sensor/a"]
        with pytest.raises(SourceUnavailableError):
            emit(message_id="early", payload=None)
        sources.stop_accepting()
        with pytest.raises(RuntimeError, match="已经停止"):
            await sources.start()
        await sources.stop()
        await sources.clean()
        with pytest.raises(RuntimeError):
            await sources.prepare()
        assert sources.records.read() == ()
        assert ctx.get(SOURCE_STATUS, location={"source_id": "sensor/a"}) == {
            "definition_id": str(SOURCE),
            "status": "closed",
            "accepting": False,
            "error": None,
        }

    asyncio.run(scenario())


def test_context_callback_failure_closes_only_its_source_and_is_retained(environment):
    registry, ctx, _, sources, _, events = environment
    original = registry.get(SOURCE).target.factory

    async def factory(**kwargs):
        instance = await original(**kwargs)

        async def run():
            try:
                await asyncio.Event().wait()
            finally:
                events.append(("callback", "cancelled"))

        def changed():
            raise RuntimeError("私有错误正文")

        return replace(instance, run=run, on_context_change=changed)

    sources.add(SOURCE, source_id="broken", factory=factory)
    sources.add(SOURCE, source_id="healthy")

    async def scenario():
        await sources.prepare()
        await sources.start()
        await asyncio.sleep(0)
        ctx.set(SOURCE_STATUS, {}, location={"source_id": "test"})
        for _ in range(3):
            await asyncio.sleep(0)
        status = ctx.get(SOURCE_STATUS, location={"source_id": "broken"})
        assert status["error"] == "context_update_failed" and not status["accepting"]
        assert ctx.get(SOURCE_STATUS, location={"source_id": "healthy"})["accepting"]
        assert ("callback", "cancelled") in events
        await sources.stop()
        await sources.clean()
        assert ctx.get(SOURCE_STATUS, location={"source_id": "broken"})["error"] == "context_update_failed"

    asyncio.run(scenario())


@pytest.mark.parametrize("bad", [" ", "\ud800"])
def test_invalid_source_id_does_not_reserve_an_instance(environment, bad):
    _, _, _, sources, _, events = environment
    with pytest.raises((TypeError, ValueError)):
        sources.add(SOURCE, source_id=bad)
    sources.add(SOURCE, source_id="valid")
    assert events == []


@pytest.mark.parametrize("bad", [[], {"x": object()}])
def test_invalid_config_does_not_reserve_source_identity(environment, bad):
    _, _, _, sources, _, _ = environment
    with pytest.raises((TypeError, ValueError)):
        sources.add(SOURCE, source_id="same", config=bad)
    sources.add(SOURCE, source_id="same")


def test_invalid_definitions_are_rejected_by_receiver_and_runtime(environment):
    registry, _, _, sources, _, events = environment
    original = registry.get(SOURCE)
    for invalid in (replace(original, kind="tool"), replace(original, target=object())):
        registry.replace(invalid)
        result = next(item for item in inspect_admissions(registry) if item.source == SOURCE)
        assert result.status == AdmissionStatus.REJECTED
        with pytest.raises(ValueError, match="已登记"):
            sources.add(SOURCE, source_id="same")
    registry.replace(replace(original, register_to=None))
    with pytest.raises(ValueError, match="已登记"):
        sources.add(SOURCE, source_id="same")
    registry.replace(original)
    sources.add(SOURCE, source_id="same")
    with pytest.raises(ValueError, match="重复"):
        sources.add(SOURCE, source_id="same")
    with pytest.raises(KeyError):
        sources.add(Id("dev.sources:sources/missing"), source_id="other")
    assert events == []


def test_partial_connection_failure_rolls_back_and_allows_explicit_retry(environment, monkeypatch):
    _, _, hooks, sources, _, _ = environment
    original = hooks.connect

    def fail(slot, *args, **kwargs):
        if slot == STOP:
            raise RuntimeError("插槽拒绝")
        return original(slot, *args, **kwargs)

    monkeypatch.setattr(hooks, "connect", fail)
    with pytest.raises(RuntimeError, match="插槽拒绝"):
        sources.component()
    for phase in (PREPARE, START, STOP, CLEAN):
        assert hooks.for_slot(phase, "aurora_world/sources") == ()
    monkeypatch.setattr(hooks, "connect", original)
    sources.component()
    with pytest.raises(RuntimeError, match="已连接"):
        sources.component()


def test_source_binding_honors_the_registered_receivers_rejection(environment):
    registry, _, _, sources, _, events = environment
    original = registry.get(SOURCES)

    class RejectSources:
        def rejection_reason(self, entry):
            return "该宿主拒绝此来源"

    registry.replace(replace(original, target=RejectSources()))
    with pytest.raises(ValueError, match="该宿主拒绝此来源"):
        sources.add(SOURCE, source_id="same")
    registry.replace(original)
    sources.add(SOURCE, source_id="same")
    assert events == []


def test_factory_selection_is_captured_and_late_add_is_rejected(environment):
    registry, _, _, sources, captures, _ = environment
    sources.add(SOURCE, source_id="first")

    async def replacement(**kwargs):
        raise AssertionError("不应调用替换后的定义")

    registry.replace(replace(registry.get(SOURCE), target=SourceSpec(replacement)))

    async def scenario():
        await sources.prepare()
        assert "first" in captures
        with pytest.raises(RuntimeError, match="不接受新的装配"):
            sources.add(SOURCE, source_id="second")
        await sources.clean()

    asyncio.run(scenario())


@pytest.mark.parametrize("phase", ["prepare", "start"])
def test_stop_accepting_during_startup_does_not_reopen_a_retained_callback(environment, phase):
    registry, ctx, hooks, sources, _, events = environment
    emitters = []

    async def factory(*, source_id, emit, config):
        emitters.append(emit)
        if phase == "prepare":
            sources.stop_accepting()

        async def start():
            sources.stop_accepting()

        async def stop():
            events.append("stopped")

        async def close():
            events.append("closed")

        return SourceInstance(start, stop, close)

    registry.replace(replace(registry.get(SOURCE), target=SourceSpec(factory)))
    sources.add(SOURCE, source_id="a")
    sources.add(SOURCE, source_id="b")

    async def scenario():
        host = Lifecycle(ctx, hooks, [sources.component()])
        try:
            with pytest.raises(SourceUnavailableError, match="期间已停止"):
                await host.start()
        finally:
            await host.stop()
        assert host.state == "stopped"
        assert events == (["closed"] if phase == "prepare" else ["stopped", "closed", "closed"])
        for emit in emitters:
            with pytest.raises(SourceUnavailableError):
                emit(message_id="late", payload=None)

    asyncio.run(scenario())

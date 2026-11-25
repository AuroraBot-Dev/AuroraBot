"""验证包资源配置、用户文件保留、原子注入与持久化边界。"""

import asyncio
from uuid import uuid4
from zipfile import ZipFile

import pytest
from aurora_config import (
    ConfigSchema,
    ConfigSpec,
    ConfigTemplate,
    config_entries,
    configuration_component,
    load_configuration,
    plugin,
)
from aurora_core.bootstrap import bootstrap
from aurora_core.ctx import Context, ContextSnapshot, StateAddress, StateKey, StateRecord
from aurora_core.hooks import HookConnections
from aurora_core.ids import Id
from aurora_core.lifecycle import PREPARE, Lifecycle, LifecycleComponent, install_lifecycle_slots
from aurora_core.persistence import ContextPersistence
from aurora_core.registry import RegistryEntry
from aurora_core.storage import StorageService

CONFIG = Id("dev.configuration:state/options")
SECOND = Id("dev.configuration:state/bindings")
RUNTIME = Id("dev.configuration:state/runtime")


@pytest.fixture
def package(tmp_path, monkeypatch):
    def create(resources, *, zipped=False):
        name = "config_fixture_" + uuid4().hex
        if zipped:
            path = tmp_path / (name + ".zip")
            with ZipFile(path, "w") as archive:
                archive.writestr(f"{name}/__init__.py", "")
                for relative, content in resources.items():
                    archive.writestr(f"{name}/{relative}", content)
            monkeypatch.syspath_prepend(str(path))
        else:
            path = tmp_path / name
            path.mkdir()
            (path / "__init__.py").touch()
            for relative, content in resources.items():
                target = path / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
            monkeypatch.syspath_prepend(str(tmp_path))
        return name

    return create


def definitions(name, resource="config.toml", *, owner=None, validate=None):
    registry = bootstrap()
    registry.register_many(plugin().entries)
    registry.register_many(
        config_entries(
            Id("dev.configuration:configs/options"),
            ConfigSpec(CONFIG, ConfigTemplate(name, resource, owner), ConfigSchema({}, check=validate)),
            provider="测试插件",
        )
    )
    return registry


@pytest.mark.parametrize("zipped", [False, True])
@pytest.mark.parametrize("resource", ["config.toml", "config.tomls/models/profiles.toml"])
def test_copy_resources_preserves_comments_and_user_files(tmp_path, package, resource, zipped):
    content = '# 模板注释\n[primary]\nmodel = "example"\n'
    name = package({resource: content, "config/__init__.py": ""}, zipped=zipped)
    registry = definitions(name, resource)
    directory = tmp_path / "data/config"
    path = directory / CONFIG.namespace / resource.removeprefix("config.tomls/")
    records = load_configuration(registry, directory)
    assert records == (StateRecord(StateAddress(CONFIG), {"primary": {"model": "example"}}),)
    assert path.read_text(encoding="utf-8") == content
    path.write_text('# 用户注释\nselected = "fast"\n', encoding="utf-8")
    records = load_configuration(registry, directory)
    assert records[0].value == {"selected": "fast"}
    assert path.read_text(encoding="utf-8").startswith("# 用户注释")
    path.unlink()
    assert load_configuration(registry, directory)[0].value == {"primary": {"model": "example"}}


def test_explicit_owner_and_multiple_files(tmp_path, package):
    name = package({"config.tomls/first.toml": "value = 1", "config.tomls/second.toml": "value = 2"})
    registry = definitions(name, "config.tomls/first.toml", owner="dev.owner")
    registry.register_many(
        config_entries(
            Id("dev.configuration:configs/bindings"),
            ConfigSpec(SECOND, ConfigTemplate(name, "config.tomls/second.toml"), ConfigSchema({})),
            provider="测试插件",
        )
    )
    records = load_configuration(registry, tmp_path / "data")
    assert {record.address.key: record.value for record in records} == {CONFIG: {"value": 1}, SECOND: {"value": 2}}
    assert (tmp_path / "data/dev.owner/first.toml").is_file()
    assert (tmp_path / "data/dev.configuration/second.toml").is_file()


@pytest.mark.parametrize(
    "resource",
    [
        "config/options.toml",
        "../config.toml",
        "config.tomls/../a.toml",
        "config.tomls//a.toml",
        "config.tomls/a.json",
        "config.tomls/C:/a.toml",
        "config.tomls\\a.toml",
    ],
)
def test_rejects_ambiguous_or_unsafe_resource_paths(resource):
    with pytest.raises(ValueError, match="配置模板"):
        ConfigTemplate("example", resource)


def test_rejects_conflicting_forms_missing_resource_and_destination_collision(tmp_path, package):
    name = package({"config.toml": "", "config.tomls/other.toml": ""})
    with pytest.raises(ValueError, match="同时"):
        load_configuration(definitions(name), tmp_path / "both")
    name = package({"config.tomls/other.toml": ""})
    with pytest.raises(ValueError, match="不存在"):
        load_configuration(definitions(name), tmp_path / "missing")
    name = package({"config.toml": ""})
    registry = definitions(name)
    registry.register_many(
        config_entries(
            Id("dev.configuration:configs/bindings"),
            ConfigSpec(SECOND, ConfigTemplate(name), ConfigSchema({})),
            provider="测试插件",
        )
    )
    with pytest.raises(ValueError, match="重复"):
        load_configuration(registry, tmp_path / "collision")
    assert not (tmp_path / "collision").exists()


def test_invalid_toml_reports_path_without_configuration_contents(tmp_path, package):
    name = package({"config.toml": 'secret = "sensitive-value'})
    with pytest.raises(ValueError, match="config.toml") as caught:
        load_configuration(definitions(name), tmp_path / "data")
    assert "sensitive-value" not in str(caught.value)


def test_configure_validates_all_records_before_commit_and_notification():
    registry = bootstrap()

    def validate(value):
        if not isinstance(value, dict):
            raise TypeError("需要对象")

    for key in (CONFIG, SECOND):
        registry.register(RegistryEntry(key, "state_key", StateKey(validate, persistent=False), "测试插件"))
    ctx = Context(registry)
    ctx.set(CONFIG, {"old": True})
    observations = []
    ctx.subscribe(lambda change: observations.append((ctx.get(CONFIG), ctx.get(SECOND))))
    with pytest.raises(TypeError, match="需要对象"):
        ctx.configure((StateRecord(StateAddress(CONFIG), {"new": True}), StateRecord(StateAddress(SECOND), 1)))
    assert ctx.get(CONFIG) == {"old": True} and observations == []
    ctx.configure((StateRecord(StateAddress(CONFIG), {}), StateRecord(StateAddress(SECOND), {})))
    assert observations == [({}, {}), ({}, {})]
    assert ctx.snapshot(persistent_only=True).records == ()


@pytest.mark.parametrize("action", ["set", "configure", "delete"])
def test_configure_queues_all_changes_before_reentrant_writes(action):
    registry = bootstrap()
    for key in (CONFIG, SECOND):
        registry.register(RegistryEntry(key, "state_key", StateKey(persistent=False), "测试插件"))
    ctx = Context(registry)
    changes, mirror = [], {}

    def write(change):
        if change.address.key == CONFIG:
            if action == "configure":
                ctx.configure((StateRecord(StateAddress(SECOND), "新值"),))
            elif action == "delete":
                ctx.delete(SECOND)
            else:
                ctx.set(SECOND, "新值")

    def observe(change):
        changes.append(change)
        if change.action == "delete":
            mirror.pop(change.address)
        else:
            mirror[change.address] = change.value

    ctx.subscribe(write)
    ctx.subscribe(observe)
    ctx.configure((StateRecord(StateAddress(CONFIG), {}), StateRecord(StateAddress(SECOND), "旧值")))
    assert [change.revision for change in changes] == [1, 2, 3]
    assert changes[1].value == "旧值" and changes[2].previous == "旧值"
    assert mirror == {record.address: record.value for record in ctx.snapshot().records}


def test_template_states_require_explicit_non_persistence(tmp_path, package):
    name = package({"config.toml": ""})
    registry = definitions(name)
    registry.replace(RegistryEntry(CONFIG, "state_key", StateKey(), "测试插件"))
    with pytest.raises(ValueError, match="非持久"):
        load_configuration(registry, tmp_path / "data")


def test_cross_file_validation_finishes_before_any_configuration_is_injected(tmp_path, package):
    from aurora_config.service import ConfigurationService

    name = package({"config.tomls/options.toml": 'selected = "missing"', "config.tomls/bindings.toml": "known = true"})
    registry = definitions(name, "config.tomls/options.toml")
    observations = []

    def check(values):
        assert values[CONFIG] == {"selected": "missing"}
        assert values[SECOND] == {"known": True}
        raise ValueError("引用不存在")

    registry.register_many(
        config_entries(
            Id("dev.configuration:configs/bindings"),
            ConfigSpec(SECOND, ConfigTemplate(name, "config.tomls/bindings.toml"), ConfigSchema({}), check=check),
            provider="测试插件",
        )
    )
    ctx = Context(registry)
    ctx.subscribe(observations.append)
    storage = StorageService(tmp_path / "data")
    try:
        with pytest.raises(ValueError, match="bindings.toml.*引用不存在"):
            ConfigurationService(registry, ctx, storage).configure()
        assert ctx.list() == () and observations == []
    finally:
        storage.close()
        ctx.close()


def test_lifecycle_rebuilds_configuration_before_prepare_and_excludes_snapshot(tmp_path, package):
    name = package({"config.toml": 'selected = "initial"\nobsolete = true\n'})
    prepared = []

    def environment():
        def validate(value):
            if not isinstance(value, dict):
                raise TypeError("需要对象")

        registry = definitions(name, validate=validate)
        registry.register(RegistryEntry(RUNTIME, "state_key", StateKey(), "测试插件"))
        install_lifecycle_slots(registry)
        ctx = Context(registry)
        hooks = HookConnections(registry)
        storage = StorageService(tmp_path / "data")
        store = storage.snapshot_store()
        identity = Id("dev.configuration:handlers/prepare")
        registry.register(
            RegistryEntry(
                identity,
                "hook_handler",
                lambda: prepared.append((ctx.get(CONFIG), ctx.get(RUNTIME))),
                "测试插件",
                slot=PREPARE,
            )
        )
        hooks.connect(PREPARE, identity, slot_instance="app", handler_instance="app")
        lifecycle = Lifecycle(
            ctx,
            hooks,
            [configuration_component(registry, ctx, hooks, storage), LifecycleComponent("app")],
            persistence=ContextPersistence(ctx, store),
            storage=storage,
        )
        return ctx, storage, store, lifecycle

    async def scenario():
        ctx, _, store, lifecycle = environment()
        store.save(
            ContextSnapshot(9, (StateRecord(StateAddress(CONFIG), "旧格式配置"), StateRecord(StateAddress(RUNTIME), 7)))
        )
        await lifecycle.start()
        assert prepared == [({"selected": "initial", "obsolete": True}, 7)]
        ctx.set(CONFIG, {"selected": "temporary"}, location={"scope": "test"})
        ctx.set(CONFIG, {"selected": "temporary"})
        ctx.set(RUNTIME, 8)
        await lifecycle.stop()
        assert store.load() == (StateRecord(StateAddress(RUNTIME), 8),)
        path = tmp_path / "data/config/dev.configuration/config.toml"
        assert "initial" in path.read_text(encoding="utf-8")
        path.write_text('selected = "edited"\n', encoding="utf-8")
        ctx, _, _, lifecycle = environment()
        await lifecycle.start()
        assert prepared[-1] == ({"selected": "edited"}, 8)
        assert ctx.list(key=CONFIG) == (StateAddress(CONFIG),)
        await lifecycle.stop()
        path.write_text("invalid = [", encoding="utf-8")
        ctx, storage, _, lifecycle = environment()
        with pytest.raises(ValueError, match="TOML"):
            await lifecycle.start()
        assert len(prepared) == 2
        assert lifecycle.state == "stopped"
        with pytest.raises(RuntimeError, match="关闭"):
            storage.configuration_directory()

    asyncio.run(scenario())

"""核对清单、静态目录与真实实例端口，不启动模型或外部服务。"""

import asyncio
import json
from pathlib import Path
from typing import cast

import pytest
from aurora_agent.plugins.model import plugin as model_plugin
from aurora_agent.plugins.model._meta import EXECUTE
from aurora_config import plugin as config_plugin
from aurora_config.editor_contract import describe_configuration
from aurora_control import ExecutionPlug, ExecutionRequest, ExecutionSlot, StateBinding
from aurora_control import plugin as control_plugin
from aurora_control._meta import SERIAL_CHILDREN, SERIAL_EXECUTE
from aurora_core.bootstrap import bootstrap
from aurora_core.ctx import Context, StateKey
from aurora_core.discovery import register_plugins
from aurora_core.hooks import HookConnections
from aurora_core.ids import Id
from aurora_core.registry import RegistryEntry
from aurora_core.storage import StorageService
from aurora_meta_build import generate, outputs
from aurora_model.testing import FakeModel, FakeReply

ROOT = Path(__file__).resolve().parents[2]


def test_manifest_generated_catalog_and_runtime_definitions_agree():
    for name, factory in (
        ("aurora_config", config_plugin),
        ("aurora_control", control_plugin),
        ("aurora_agent", model_plugin),
    ):
        root = ROOT / "packages" / name
        generate(root, check=True)
        catalog = json.loads((root / "plugin.meta.json").read_text(encoding="utf-8"))
        assert catalog["schema_version"] == 2
        (manifest,) = catalog["manifests"].values()
        exported = factory()
        definitions = {item["id"]: item for item in manifest["definitions"].values()}
        assert {str(entry.id) for entry in exported.entries} == definitions.keys()
        for entry in exported.entries:
            declaration = definitions[str(entry.id)]
            owner = manifest["plugins"][declaration["plugin"]]
            assert entry.provider == owner.get("provider", owner["entry_point"])
            assert entry.kind == declaration["kind"]
            receiver = declaration.get("register_to")
            assert entry.register_to == (Id(receiver["id"]) if receiver else None)
            assert entry.slot is None
        if name == "aurora_config":
            assert manifest["contracts"]["configuration_http"]["content"] == describe_configuration()


def test_multiple_manifests_keep_local_symbols_and_parameter_contracts_separate(tmp_path):
    import shutil

    (tmp_path / "pyproject.toml").write_text(
        """
[project]
name = "metadata-fixture"
version = "0.1.0"
[project.entry-points."aurora.plugins"]
aurora_config = "aurora_config:plugin"
"aurora_agent.model" = "aurora_agent.plugins.model:plugin"
[[tool.aurora-meta-build.plugins]]
manifest = "src/aurora_config/plugin.meta.toml"
module = "src/aurora_config/_meta.py"
[[tool.aurora-meta-build.plugins]]
manifest = "src/aurora_agent/plugins/model/plugin.meta.toml"
module = "src/aurora_agent/plugins/model/_meta.py"
""",
        encoding="utf-8",
    )
    for package, relative, symbol in (
        ("aurora_config", "", "CONFIGS"),
        ("aurora_agent", "plugins/model", "MODEL_CALL"),
    ):
        source = ROOT / "packages" / package / "src" / package / relative
        target = tmp_path / "src" / package / relative
        target.mkdir(parents=True)
        for filename in ("plugin.meta.toml", "editor_contract.py", "options.schema.json"):
            if (source / filename).exists():
                shutil.copyfile(source / filename, target / filename)
        manifest = target / "plugin.meta.toml"
        manifest.write_text(manifest.read_text(encoding="utf-8").replace(symbol, "ENTRY"), encoding="utf-8")
    generated = outputs(tmp_path)
    modules = [value for path, value in generated.items() if path.suffix == ".py"]
    assert len(modules) == 2 and all("ENTRY = Id(" in module for module in modules)
    assert "org.aurora.config:registries/configs" in modules[0]
    assert "org.aurora.agent:handlers/model_call" in modules[1]
    catalog = json.loads(generated[tmp_path / "plugin.meta.json"])
    assert len(catalog["manifests"]) == 2
    generate(tmp_path)
    generate(tmp_path, check=True)
    module = tmp_path / "src/aurora_config/_meta.py"
    module.write_text(module.read_text(encoding="utf-8").replace("org.aurora.config", "dev.stale"), encoding="utf-8")
    with pytest.raises(ValueError, match="过期"):
        generate(tmp_path, check=True)


def test_serial_and_model_exports_preserve_state_handshake_and_explicit_resource_binding(tmp_path):
    config, control, model = config_plugin(), control_plugin(), model_plugin()
    registry = bootstrap()
    register_plugins(registry, (config, control, model))
    key = Id("dev.metadata:state/work")
    registry.register(RegistryEntry(key, "state_key", StateKey(), "test"))
    ctx, hooks = Context(registry), HookConnections(registry)
    states = {role: StateBinding(key, (("role", role),)) for role in ("input", "output")}
    services = {"ctx": ctx, "hooks": hooks, "registry": registry, "storage": StorageService(tmp_path)}
    configuration = config.components["configuration"].create(services, instance_id="configuration")
    assert configuration.exports.resources["configuration"] is configuration.instance
    serial = control.components["serial"].create(services, instance_id="sequence", states=states)
    call = model.components["model_call"].create(
        services, instance_id="inference", states=states, options={"streaming": False}
    )
    assert not hooks.for_slot(SERIAL_CHILDREN, "sequence")
    with pytest.raises(KeyError, match="chat"):
        call.bind({})
    client = FakeModel(lambda _: FakeReply(("已绑定",)))
    call.bind({"chat": client})
    slot = cast(ExecutionSlot, serial.exports.slots[SERIAL_CHILDREN])
    plug = cast(ExecutionPlug, call.exports.plugs[EXECUTE])
    link = slot.connect(plug)
    assert link.slot_states == states == plug.states
    assert slot is serial.instance.slot
    request = ExecutionRequest("run")
    states["input"].set(ctx, request, {"messages": [{"role": "user", "content": "测试"}]})

    async def run():
        await cast(ExecutionPlug, serial.exports.plugs[SERIAL_EXECUTE])(request)
        assert cast(dict, states["output"].get(ctx, request))["text"] == "已绑定"
        assert not client.closed
        await client.aclose()

    try:
        asyncio.run(run())
    finally:
        hooks.close()
        ctx.close()

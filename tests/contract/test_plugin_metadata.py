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
from aurora_control import ExecutionPlug, ExecutionRequest, ExecutionSlot
from aurora_control import plugin as control_plugin
from aurora_control._meta import SERIAL_CHILDREN, SERIAL_EXECUTE
from aurora_core.ctx import StateKey
from aurora_core.ids import Id
from aurora_core.registry import RegistryEntry
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


def test_host_file_assembly_connects_real_ports_states_and_resource_owner(tmp_path):
    import tomli_w
    from aurora_core.components import ComponentDeclaration, ComponentExport, ComponentFactory, InstanceExport
    from aurora_core.discovery import Plugin
    from aurora_core.lifecycle import CLEAN
    from aurora_host import Host, read_assembly

    client = FakeModel(lambda _: FakeReply(("已绑定",)))
    key = Id("dev.metadata:state/work")
    close = Id("dev.metadata:handlers/close")
    resource = Plugin(
        "test.resource",
        (
            RegistryEntry(key, "state_key", StateKey(), "test.resource"),
            RegistryEntry(
                close,
                "hook_handler",
                client.aclose,
                "test.resource",
                register_to=Id("org.aurora.core:registries/hook_handlers"),
            ),
        ),
        components={
            "client": ComponentExport(
                ComponentFactory(
                    lambda: client, lambda value: InstanceExport(resources={"chat": value}, plugs={close: value.aclose})
                ),
                ComponentDeclaration(resources=("chat",), plugs=(close,)),
            )
        },
    )
    states = {
        "input": {"key": str(key), "scope": "instance", "location": {"instance_id": "conversation", "part": "input"}},
        "output": {"key": str(key), "scope": "run", "location": {"part": "output"}},
    }
    path = tmp_path / "assembly.toml"
    path.write_text(
        tomli_w.dumps(
            {
                "schema_version": 2,
                "plugins": ["aurora_control", "aurora_agent.model", "test.resource"],
                "instances": {
                    "sequence": {
                        "plugin": "aurora_control",
                        "component": "serial",
                        "states": states,
                        "depends_on": ["inference"],
                    },
                    "inference": {
                        "plugin": "aurora_agent.model",
                        "component": "model_call",
                        "states": states,
                        "options": {"streaming": False},
                        "resources": {"chat": {"instance": "client", "export": "chat"}},
                        "depends_on": ["client"],
                    },
                    "client": {"plugin": "test.resource", "component": "client"},
                },
                "connections": [
                    {
                        "plug": {"instance": "inference", "id": str(EXECUTE)},
                        "slot": {"instance": "sequence", "id": str(SERIAL_CHILDREN)},
                        "priority": 7,
                    },
                    {
                        "plug": {"instance": "client", "id": str(close)},
                        "slot": {"instance": "client", "id": str(CLEAN)},
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    async def run():
        host = Host.create(read_assembly(path), [resource], tmp_path / "data", workspace_root=tmp_path)
        try:
            sequence, call = (host.graph.instances[name] for name in ("sequence", "inference"))
            slot = cast(ExecutionSlot, sequence.exports.slots[SERIAL_CHILDREN])
            plug = cast(ExecutionPlug, call.exports.plugs[EXECUTE])
            assert slot is sequence.instance.slot
            assert host.graph.instances["client"].exports.resources["chat"] is client
            assert len(host.graph.connections) == 2
            await host.start()
            first, second = ExecutionRequest("first"), ExecutionRequest("second")
            plug.states["input"].set(host.ctx, first, {"messages": [{"role": "user", "content": "测试"}]})
            assert plug.states["input"].address(first) == plug.states["input"].address(second)
            assert plug.states["output"].address(first) != plug.states["output"].address(second)
            for request in (first, second):
                await host.run(cast(ExecutionPlug, sequence.exports.plugs[SERIAL_EXECUTE]), request)
                assert cast(dict, plug.states["output"].get(host.ctx, request))["text"] == "已绑定"
            assert not client.closed
        finally:
            await host.stop()
        assert client.closed

    asyncio.run(run())

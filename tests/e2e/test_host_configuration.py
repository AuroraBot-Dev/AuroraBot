"""验证宿主 TOML 在发现前加载，配置在组件 prepare 前注入。"""

import asyncio
import json
from io import StringIO

import pytest
import tomli_w
from aurora_cli.commander import run_cli
from aurora_config import read_toml
from aurora_core import Id, entry_from, plug
from aurora_core.components import ComponentDeclaration, ComponentExport, ComponentFactory, InstanceExport
from aurora_core.discovery import Plugin
from aurora_core.lifecycle import PREPARE
from aurora_host.configuration import initialize_host_config

CONFIG = Id("org.aurora.cli:state/config")


def write_host(root, content):
    directory = root / "config"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "host.toml").write_text(content, encoding="utf-8")


def test_host_enables_plugins_before_discovery_without_initializing_resources(tmp_path, monkeypatch):
    monkeypatch.setenv("COLUMNS", "160")
    content = 'assembly_file = "app.toml"\n'
    write_host(tmp_path, content)
    (tmp_path / "config/app.toml").write_text(
        'schema_version = 2\nplugins = ["aurora_config", "aurora_model", "aurora_model.configuration", "aurora_model.litellm"]\n[instances]\n',
        encoding="utf-8",
    )
    output = StringIO()
    asyncio.run(run_cli(["-d", str(tmp_path), "id", "list"], output=output))
    assert "org.aurora.model:state/config" in output.getvalue()
    assert not (tmp_path / "framework").exists()
    assert not (tmp_path / "config/org.aurora.model").exists()
    assert not (tmp_path / "config/org.aurora.mcp").exists()
    assert (tmp_path / "config/host.toml").read_text(encoding="utf-8") == content


def test_host_default_assembly_reads_toml_before_prepare_and_keeps_runtime_edits_transient(tmp_path):
    initialize_host_config(tmp_path / "config")
    assembly_path = tmp_path / "config/assembly.toml"
    plan = read_toml(assembly_path)
    plan["plugins"].append("probe")
    plan["instances"]["app"] = {"plugin": "probe", "component": "probe"}
    plan["connections"].append(
        {
            "plug": {"instance": "app", "id": "dev.configuration:handlers/prepare"},
            "slot": {"instance": "app", "id": str(PREPARE)},
        }
    )
    assembly_path.write_text(tomli_w.dumps(plan), encoding="utf-8")
    directory = tmp_path / "config/org.aurora.cli"
    directory.mkdir()
    path = directory / "plugin.config.toml"
    path.write_text('value = "file"\n', encoding="utf-8")
    observations = []

    def factory(*, ctx):
        @plug("dev.configuration:handlers/prepare")
        def prepare():
            observations.append(ctx.get(CONFIG))
            ctx.set(CONFIG, {"value": "runtime"})

        return prepare

    definition = entry_from(factory(ctx=None), provider="probe")
    plugin = Plugin(
        "probe",
        (definition,),
        components={
            "probe": ComponentExport(
                ComponentFactory(factory, lambda prepare: InstanceExport(plugs={definition.id: prepare})),
                ComponentDeclaration(inject=("ctx",), plugs=(definition.id,)),
            )
        },
    )
    for _ in range(2):
        output = StringIO()
        asyncio.run(run_cli(["-d", str(tmp_path), "ctx/get", str(CONFIG)], plugins=[plugin], output=output))
        assert json.loads(output.getvalue()) == {"value": "runtime"}
    assert observations == [{"value": "file"}, {"value": "file"}]
    assert path.read_text(encoding="utf-8") == 'value = "file"\n'


def test_explicit_assembly_file_overrides_host_selection(tmp_path):
    write_host(tmp_path, 'assembly_file = "missing.toml"\n')
    path = tmp_path / "app.toml"
    path.write_text("schema_version = 2\nplugins = []\n[instances]\n", encoding="utf-8")
    assert asyncio.run(run_cli(["-d", str(tmp_path), "--assembly-file", str(path), "ctx/list"], output=StringIO())) == 0


@pytest.mark.parametrize(
    "content",
    [
        'plugins = "bad"',
        "plugins = [1]",
        "assembly = 1",
        "unknown = true",
        "invalid = [",
        'assembly_file = "assembly.toml"\nassembly = "dev.test:assemblies/app"',
        'assembly_file = "assembly.toml"\nplugins = ["aurora_config"]',
    ],
)
def test_invalid_host_configuration_fails_before_storage_initialization(tmp_path, content):
    write_host(tmp_path, content)
    with pytest.raises(ValueError):
        asyncio.run(run_cli(["-d", str(tmp_path), "ctx/list"], output=StringIO()))
    assert not (tmp_path / "framework").exists()

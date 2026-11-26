"""验证宿主 TOML 在发现前加载，配置在组件 prepare 前注入。"""

import asyncio
import json
from io import StringIO

import pytest
from aurora_cli.commander import run_cli
from aurora_core import Id, entry_from, hook_handler
from aurora_core.discovery import Plugin
from aurora_core.lifecycle import PREPARE, LifecycleComponent
from aurora_core.registry import RegistryEntry

CONFIG = Id("org.aurora.cli:state/config")


def write_host(root, content):
    directory = root / "config"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "host.toml").write_text(content, encoding="utf-8")


def test_host_enables_plugins_before_discovery_without_initializing_resources(tmp_path, monkeypatch):
    monkeypatch.setenv("COLUMNS", "160")
    content = 'plugins = ["aurora_adapter.model"]\nassembly = "dev.missing:assemblies/app"\n'
    write_host(tmp_path, content)
    output = StringIO()
    asyncio.run(run_cli(["-d", str(tmp_path), "id", "list"], output=output))
    assert "org.aurora.adapter:state/model/config" in output.getvalue()
    assert not (tmp_path / "framework").exists()
    assert not (tmp_path / "config/org.aurora.adapter").exists()
    assert (tmp_path / "config/host.toml").read_text(encoding="utf-8") == content


def test_host_default_assembly_reads_toml_before_prepare_and_keeps_runtime_edits_transient(tmp_path):
    assembly = Id("dev.configuration:assemblies/default")
    write_host(tmp_path, f'assembly = "{assembly}"\n')
    directory = tmp_path / "config/org.aurora.cli"
    directory.mkdir()
    path = directory / "config.toml"
    path.write_text('value = "file"\n', encoding="utf-8")
    observations = []

    def factory(*, registry, ctx, hooks, storage, workspace_root):
        @hook_handler("dev.configuration:handlers/prepare", slot=PREPARE)
        def prepare():
            observations.append(ctx.get(CONFIG))
            ctx.set(CONFIG, {"value": "runtime"})

        entry = entry_from(prepare, provider="测试插件")
        registry.register(entry)
        hooks.connect(PREPARE, entry.id, slot_instance="app", handler_instance="app")
        return [LifecycleComponent("app")]

    plugin = Plugin("测试插件", (RegistryEntry(assembly, "assembly", factory, "测试插件"),))
    for _ in range(2):
        output = StringIO()
        asyncio.run(run_cli(["-d", str(tmp_path), "ctx/get", str(CONFIG)], plugins=[plugin], output=output))
        assert json.loads(output.getvalue()) == {"value": "runtime"}
    assert observations == [{"value": "file"}, {"value": "file"}]
    assert path.read_text(encoding="utf-8") == 'value = "file"\n'


@pytest.mark.parametrize(
    "arguments", [["--assembly", "dev.selected:assemblies/app", "ctx/list"], ["run", "dev.selected:assemblies/app"]]
)
def test_explicit_plugin_and_assembly_selection_override_host_defaults(tmp_path, monkeypatch, arguments):
    write_host(tmp_path, 'plugins = ["missing-plugin"]\nassembly = "dev.default:assemblies/app"\n')
    selections = []

    async def execute(context, command, values, **options):
        selections.append(options["assembly"])
        assert context.registry.get(Id("org.aurora.adapter:adapters/model/litellm/chat"))
        return 0

    monkeypatch.setattr("aurora_cli.host.execute", execute)
    asyncio.run(run_cli(["-d", str(tmp_path), "--plugin", "aurora_adapter.model", *arguments], output=StringIO()))
    assert selections == [Id("dev.selected:assemblies/app")]


@pytest.mark.parametrize(
    "content", ['plugins = "bad"', "plugins = [1]", "assembly = 1", "unknown = true", "invalid = ["]
)
def test_invalid_host_configuration_fails_before_storage_initialization(tmp_path, content):
    write_host(tmp_path, content)
    with pytest.raises(ValueError):
        asyncio.run(run_cli(["-d", str(tmp_path), "ctx/list"], output=StringIO()))
    assert not (tmp_path / "framework").exists()

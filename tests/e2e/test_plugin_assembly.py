"""真实配置插件经集中配置完成发现、接线、ctx 注入和关闭。"""

import asyncio
import json
from importlib.resources import files
from io import StringIO

import pytest
from aurora_cli.commander import run_cli
from aurora_cli.declarations import command_plugin
from aurora_config import CONFIGURATION, plugin, read_toml
from aurora_world.configuration import CONFIG_STATE, SOURCE_CONFIG


def assembly_file(tmp_path, *, world=False, connected=True):
    content = files("aurora_config").joinpath("assembly.toml").read_text(encoding="utf-8")
    # 使用任意应用实例名，防止隐藏路径按 aurora_config 再创建一个实例。
    content = content.replace("instances.aurora_config", "instances.loader").replace(
        'instance = "aurora_config"', 'instance = "loader"'
    )
    if world:
        content = content.replace(
            'plugins = ["aurora_config"]', 'plugins = ["aurora_config", "aurora_world", "aurora_world.configuration"]'
        )
    if not connected:
        content = content.split("[[connections]]")[0]
    path = tmp_path / "assembly.toml"
    path.write_text(content, encoding="utf-8")
    return path


def test_file_assembly_loads_world_configuration_and_closes_editor(tmp_path):
    assembly = assembly_file(tmp_path, world=True)
    output = StringIO()
    endpoints = []

    def observe(context):
        endpoint = context.registry.get(CONFIGURATION).target
        endpoints.append(endpoint)
        assert endpoint.files is not None
        assert "org.aurora.world:configs/sources" in {item["id"] for item in endpoint.files.list()}

    assembly.write_text(
        assembly.read_text(encoding="utf-8").replace("plugins = [", 'plugins = ["probe", '), encoding="utf-8"
    )
    probe = command_plugin("probe", {"probe": {"help": "检查配置服务", "executor": observe, "runtime": True}})
    data = tmp_path / "data"
    arguments = ["--data-dir", str(data), "--assembly-file", str(assembly)]
    asyncio.run(run_cli([*arguments, "probe"], plugins=[probe], output=output))
    assert endpoints[0].files is None
    assembly_file(tmp_path, world=True)
    path = data / "config/org.aurora.world/config.toml"
    expected = SOURCE_CONFIG.parse(read_toml(path))
    output = StringIO()
    asyncio.run(run_cli([*arguments, "ctx/get", str(CONFIG_STATE)], output=output))
    assert json.loads(output.getvalue()) == expected
    snapshot = json.loads((data / "framework/ctx.json").read_text(encoding="utf-8"))
    assert str(CONFIG_STATE) not in {entry["id"] for entry in snapshot["entries"]}
    assert not (data / "config/org.aurora.bot").exists()


def test_missing_connection_does_not_implicitly_run_configuration(tmp_path):
    assembly = assembly_file(tmp_path, world=True, connected=False)
    data = tmp_path / "data"
    output = StringIO()
    asyncio.run(run_cli(["-d", str(data), "--assembly-file", str(assembly), "ctx/list"], output=output))
    assert json.loads(output.getvalue()) == []
    assert not (data / "config/org.aurora.world").exists()
    assembly = assembly_file(tmp_path, world=True)
    assembly.write_text(
        assembly.read_text(encoding="utf-8").replace(
            "org.aurora.core:lifecycle/config", "org.aurora.core:lifecycle/start"
        ),
        encoding="utf-8",
    )
    output = StringIO()
    asyncio.run(
        run_cli(["-d", str(data), "--assembly-file", str(assembly), "ctx/get", str(CONFIG_STATE)], output=output)
    )
    assert json.loads(output.getvalue())["sources"] == []
    assembly.write_text("schema_version = 1\nplugins = []\n[instances]\n", encoding="utf-8")
    output = StringIO()
    asyncio.run(run_cli(["--assembly-file", str(assembly), "id/list"], plugins=[plugin()], output=output))
    assert str(CONFIGURATION) not in output.getvalue()


def test_host_selects_relative_assembly_file_and_rejects_mixed_selection(tmp_path):
    path = assembly_file(tmp_path)
    root = tmp_path / "data"
    config = root / "config"
    config.mkdir(parents=True)
    (config / "host.toml").write_text('assembly_file = "../../assembly.toml"\n', encoding="utf-8")
    output = StringIO()
    asyncio.run(run_cli(["-d", str(root), "ctx/list"], output=output))
    assert "org.aurora.cli:state/config" in output.getvalue()
    for arguments in (
        ["--assembly", "dev.test:assemblies/app", "ctx/list"],
        ["--plugin", "aurora_config", "ctx/list"],
        ["run", "dev.test:assemblies/app"],
    ):
        with pytest.raises(SystemExit):
            asyncio.run(run_cli(["--assembly-file", str(path), *arguments], output=StringIO()))


def test_failed_assembly_releases_storage_for_corrected_selection(tmp_path):
    path = assembly_file(tmp_path)
    path.write_text(
        path.read_text(encoding="utf-8").replace('plugins = ["aurora_config"]', "plugins = []"), encoding="utf-8"
    )
    data = tmp_path / "data"
    with pytest.raises(KeyError, match="aurora_config"):
        asyncio.run(run_cli(["-d", str(data), "--assembly-file", str(path), "ctx/list"], output=StringIO()))
    # 出错后存储已释放，改正配置可再次启动相同目录。
    path = assembly_file(tmp_path)
    assert asyncio.run(run_cli(["-d", str(data), "--assembly-file", str(path), "ctx/list"], output=StringIO())) == 0

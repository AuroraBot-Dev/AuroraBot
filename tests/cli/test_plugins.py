"""内置、目录与安装入口共用声明；在产生效果前完成整份目录校验。"""

from __future__ import annotations

import json
from dataclasses import replace
from typing import TYPE_CHECKING

import pytest

from aurora_cli.commander import run
from aurora_cli.commands import start
from aurora_cli.contracts.config import AuroraConfig, ConfigSpec
from aurora_cli.plugins import CliPlugin, CommandContribution, ConfigContribution, ConfigFile, command_plugin
from aurora_cli.plugins.catalog import load_plugins
from aurora_cli.plugins.discovery import DiscoveredPlugin
from aurora_cli.utils.process import EXIT_CONFIG_ERROR
from aurora_kernel import Context, ModuleSpec, namespace
from aurora_kernel.declaration import Manifest
from aurora_kernel.discovery import StaticSource
from tests.cli.plugin_support import write_plugin

if TYPE_CHECKING:
    import argparse
    from pathlib import Path

    from aurora_cli.plugins.catalog import PluginCatalog


@pytest.fixture(autouse=True)
def isolated_entry_points(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("aurora_kernel.discovery.entry_points", lambda *, group: ())


def test_local_plugin_joins_help_config_editing_and_command_execution(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_plugin(tmp_path)
    args = ["--root", str(tmp_path)]
    with pytest.raises(SystemExit) as exited:
        run([*args, "--help"])
    assert exited.value.code == 0
    help_text = capsys.readouterr().out
    assert "greet" in help_text and "start" in help_text and "config" in help_text
    assert not (tmp_path / "config").exists()
    assert not (tmp_path / "settings").exists()

    assert run([*args, "config", "extra", "--missing"]) == 0
    assert json.loads(capsys.readouterr().out) == {
        "extra": ["settings/custom.toml", "settings/extra/note.md"],
    }
    assert run([*args, "config", "extra", "--init"]) == 0
    assert not (tmp_path / "config").exists()
    assert (tmp_path / "settings/extra/note.md").read_text(encoding="utf-8") == "配套资源\n"
    capsys.readouterr()

    assert run([*args, "config", "extra", "--raw"]) == 0
    assert "来自插件" in capsys.readouterr().out
    assert run([*args, "config", "extra", "--set", "extra.message=个人设置"]) == 0
    assert "settings/custom.toml" in capsys.readouterr().out
    assert run([*args, "config", "extra", "--init"]) == 0
    capsys.readouterr()
    for _ in range(2):
        assert run([*args, "greet"]) == 0
        assert capsys.readouterr().out.strip() == "个人设置 1"


def test_start_uses_the_same_discovered_config_objects(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_plugin(tmp_path)
    observed: list[str] = []
    original_load = start._load_config

    def tracked_load(root: Path, catalog: PluginCatalog) -> AuroraConfig:
        config = original_load(root, catalog)
        value = config.get(catalog.configs.spec("extra"))
        assert config.resolve(type(value)) is value
        observed.append(value.message)
        return config

    async def fake_runtime(config: AuroraConfig, *, headless: bool) -> None:
        assert "extra" in config.names

    monkeypatch.setattr(start, "_load_config", tracked_load)
    monkeypatch.setattr(start, "configure_project_logging", lambda _config: None)
    monkeypatch.setattr(start, "_run_runtime", fake_runtime)
    assert run(["--root", str(tmp_path), "start", "--headless"]) == 0
    assert observed == ["来自插件"]


def test_root_selection_has_no_global_catalog_or_config_cache(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    first, second = tmp_path / "first", tmp_path / "second"
    write_plugin(first, "第一个目录")
    write_plugin(second, "第二个目录")
    for root in (first, second, first):
        assert run(["--root", str(root), "config", "extra", "--init"]) == 0
        capsys.readouterr()
        assert run(["--root", str(root), "greet"]) == 0
        expected = "第一个目录" if root == first else "第二个目录"
        assert capsys.readouterr().out.strip() == f"{expected} 1"


def test_help_does_not_read_personal_config_or_construct_plugins(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    directory = write_plugin(tmp_path)
    path = directory / "module.py"
    path.write_text(path.read_text().replace('ctx["test.extra"]["calls"] = 0', 'raise RuntimeError("不能构造")'))
    (tmp_path / "settings").mkdir()
    (tmp_path / "settings/custom.toml").write_text("broken = [")
    with pytest.raises(SystemExit) as exited:
        run(["--root", str(tmp_path), "greet", "--help"])
    assert exited.value.code == 0
    assert "greet" in capsys.readouterr().out


def test_installed_entry_point_uses_the_same_protocol_and_detects_builtin_collision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    called: list[Path] = []

    def execute(arguments: argparse.Namespace) -> int:
        called.append(arguments.root)
        return 0

    class Entry:
        name = "installed"
        plugin = command_plugin("test.installed", {"name": "installed"}, execute)

        def load(self) -> CliPlugin:
            return self.plugin

    entry = Entry()
    monkeypatch.setattr(
        "aurora_kernel.discovery.entry_points",
        lambda *, group: (entry,) if group == "aurora_cli_plugin" else (),
    )
    assert run(["--root", str(tmp_path), "installed"]) == 0
    assert called == [tmp_path]
    entry.plugin = command_plugin("test.installed", {"name": "start"}, execute)
    assert run(["--root", str(tmp_path), "start"]) == EXIT_CONFIG_ERROR
    error = capsys.readouterr().err
    assert "命令重复注册" in error
    assert "aurora_cli.commands.start" in error and "aurora_cli_plugin:installed" in error
    assert called == [tmp_path]
    assert not (tmp_path / "config").exists()


@pytest.mark.parametrize("failure", ["dependency", "cycle", "version", "target"])
def test_invalid_declarations_fail_before_construction(tmp_path: Path, failure: str) -> None:
    effects: list[str] = []

    @namespace("first", requires=("second",))
    def first(_ctx: Context) -> None:
        effects.append("first")

    @first.callpoint("execute")
    def execute(_ctx: Context, _arguments: argparse.Namespace) -> int:
        effects.append("execute")
        return 0

    second = ModuleSpec("second")
    if failure == "cycle":
        second = replace(second, depends=("first",))
    if failure == "version":
        second = replace(second, manifest=Manifest(kernel_api=">=999"))
    target = "first:missing" if failure == "target" else "first:execute"
    plugins = [DiscoveredPlugin(CliPlugin(first, commands=(CommandContribution({"name": "x"}, target),)), "first")]
    if failure != "dependency":
        plugins.append(DiscoveredPlugin(CliPlugin(second), "second"))
    with pytest.raises(ValueError):
        load_plugins(tmp_path, sources=(StaticSource(plugins),))
    assert effects == []
    assert not (tmp_path / "config").exists()


@pytest.mark.parametrize("path", ["../outside.toml", "/outside.toml", "C:/outside.toml", "config/../../outside", "."])
def test_plugin_config_paths_are_validated_before_writes(tmp_path: Path, path: str) -> None:
    spec = ConfigSpec("unsafe", path, parse=lambda file: file.read_text())
    plugin = CliPlugin(ModuleSpec("unsafe"), configs=(ConfigContribution(spec),))
    with pytest.raises(ValueError, match="配置路径"):
        load_plugins(tmp_path, sources=(StaticSource((DiscoveredPlugin(plugin, "unsafe"),)),))


@pytest.mark.parametrize("conflict", ["name", "path", "resource", "parent"])
def test_config_and_resource_conflicts_include_both_origins(tmp_path: Path, conflict: str) -> None:
    first = ConfigSpec("one", "settings/one.toml", parse=lambda file: file.read_text())
    name = "one" if conflict == "name" else "two"
    path = "settings/one.toml" if conflict == "path" else "settings/two.toml"
    files = ()
    if conflict in {"resource", "parent"}:
        destination = "settings/one.toml" if conflict == "resource" else "settings/one.toml/child.md"
        files = (ConfigFile(tmp_path / "template", destination),)
    second = ConfigSpec(name, path, parse=lambda file: file.read_text())
    declarations = (
        DiscoveredPlugin(CliPlugin(ModuleSpec("one"), configs=(ConfigContribution(first),)), "source-one"),
        DiscoveredPlugin(CliPlugin(ModuleSpec("two"), configs=(ConfigContribution(second, files),)), "source-two"),
    )
    with pytest.raises(ValueError, match="source-one") as error:
        load_plugins(tmp_path, sources=(StaticSource(declarations),))
    assert "source-two" in str(error.value)
    assert not (tmp_path / "settings").exists()


def test_missing_resource_fails_before_any_template_is_written(tmp_path: Path) -> None:
    directory = write_plugin(tmp_path)
    (directory / "note.md").unlink()
    assert run(["--root", str(tmp_path), "config", "--init"]) == EXIT_CONFIG_ERROR
    assert not (tmp_path / "config").exists()
    assert not (tmp_path / "settings").exists()


def test_external_config_cannot_read_or_edit_through_outside_symlink(tmp_path: Path) -> None:
    root = tmp_path / "project"
    write_plugin(root)
    outside = tmp_path / "outside"
    outside.mkdir()
    personal = outside / "custom.toml"
    original = '[extra]\nmessage = "outside"\n'
    personal.write_text(original)
    (root / "settings").symlink_to(outside, target_is_directory=True)
    for flags in (("--raw",), ("--set", "extra.message=changed"), ("--init",)):
        assert run(["--root", str(root), "config", "extra", *flags]) == EXIT_CONFIG_ERROR
    assert personal.read_text() == original


def test_version_does_not_load_a_broken_local_plugin(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    directory = tmp_path / "extensions/cli"
    directory.mkdir(parents=True)
    (directory / "broken.py").write_text('raise RuntimeError("不应导入")')
    assert run(["--root", str(tmp_path), "--version"]) == 0
    assert "AuroraBot" in capsys.readouterr().out

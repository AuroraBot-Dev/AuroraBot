"""验证 CLI 状态命令、第三方声明和装配生命周期。"""

import asyncio
import json
import logging
import os
import subprocess
import sys
import tomllib
from importlib.metadata import version
from io import StringIO
from pathlib import Path

import pytest
from aurora_cli.commander import run_cli
from aurora_core import Id, entry_from, hook_handler, operation
from aurora_core.discovery import Plugin
from aurora_core.lifecycle import PREPARE, START, STOP, LifecycleComponent
from aurora_core.registry import RegistryEntry

CONFIG = "org.aurora.cli:state/config"


@pytest.mark.parametrize("flag", ["-v", "--version"])
def test_version_exits_without_loading_plugins_or_creating_storage(tmp_path, flag):
    result = invoke("--plugin", "missing-version-test-plugin", "--data-dir", tmp_path / "data", flag)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == f"aurora {version('aurora-cli')}"
    assert not (tmp_path / "data").exists()


def invoke(*args):
    return subprocess.run(
        [sys.executable, "-m", "aurora_cli", *map(str, args)], check=False, capture_output=True, text=True, timeout=15
    )


def test_cli_configuration_rebuilds_from_toml_across_processes(tmp_path):
    def run(*args):
        result = invoke("--data-dir", tmp_path, *args)
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout)

    assert run("ctx", "set", CONFIG, '{"value":1}') is None
    assert run("ctx/get", CONFIG) == {}
    (tmp_path / "config/org.aurora.cli/config.toml").write_text("value = 3\n", encoding="utf-8")
    assert run("ctx/get", CONFIG) == {"value": 3}
    assert run("ctx/delete", CONFIG) is True
    assert run("ctx/get", CONFIG) == {"value": 3}


@pytest.mark.parametrize(
    ("options", "tracebacks", "visible"),
    [
        ([], False, True),
        (["--level", "debug"], True, True),
        (["-l", "critical"], False, False),
    ],
)
def test_cli_errors_keep_tracebacks_in_file_and_stdout_clean(tmp_path, options, tracebacks, visible):
    result = invoke(*options, "--data-dir", tmp_path, "ctx/get", CONFIG, "--location", '{"scope":"missing"}')
    assert result.returncode == 1
    assert result.stdout == ""
    assert ("KeyError" in result.stderr) is visible
    assert ("Traceback" in result.stderr) is tracebacks
    if not visible:
        assert result.stderr == ""
    content = (tmp_path / "logs" / "aurora.log").read_text(encoding="utf-8")
    assert "Traceback (most recent call last)" in content
    assert "KeyError" in content
    assert "aurora_cli.main" in content
    assert "\x1b" not in content


def test_help_and_bad_arguments_do_not_create_storage(tmp_path):
    for args in (["--help"], ["ctx", "get", "--help"]):
        result = invoke("--data-dir", tmp_path / "unused", *args)
        assert result.returncode == 0
        assert result.stdout
    for args in (
        ["ctx/set", CONFIG, "NaN"],
        ["-l"],
    ):
        result = invoke("--data-dir", tmp_path / "unused", *args)
        assert result.returncode == 2
    assert not (tmp_path / "unused").exists()


def test_project_commands_and_groups_do_not_require_host_storage(tmp_path):
    for args in (["about"], ["check", "--help"]):
        result = invoke("--root", tmp_path, *args)
        assert result.returncode == 0, result.stderr
        assert "\x1b" not in result.stdout
        assert result.stdout
    assert list(tmp_path.iterdir()) == []
    assert invoke("check", "--li").returncode == 2
    assert invoke("--roo", tmp_path, "about").returncode == 2


def test_donk_updates_versions_and_real_uv_lock(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "aurorabot-ai"\nversion = "0.1.0"\nrequires-python = ">=3.12"\n'
        'dependencies = ["aurora-core>=0.1.0"]\n'
        '[tool.uv.workspace]\nmembers = ["core"]\n'
        "[tool.uv.sources]\naurora-core = { workspace = true }\n",
        encoding="utf-8",
    )
    (tmp_path / "core").mkdir()
    (tmp_path / "core" / "pyproject.toml").write_text(
        '[project]\nname = "aurora-core"\nversion = "0.1.0"\nrequires-python = ">=3.12"\n',
        encoding="utf-8",
    )
    result = invoke("--root", tmp_path, "donk", "patch")
    assert result.returncode == 0, result.stderr
    lock = tomllib.loads((tmp_path / "uv.lock").read_text(encoding="utf-8"))
    assert {package["name"]: package["version"] for package in lock["package"]} == {
        "aurorabot-ai": "0.1.1",
        "aurora-core": "0.1.1",
    }
    root = tomllib.loads((tmp_path / "pyproject.toml").read_text(encoding="utf-8"))
    assert root["project"]["dependencies"] == ["aurora-core>=0.1.1"]


def test_extension_command_uses_operation_without_cli_types(tmp_path):
    @operation("dev.test:operations/add")
    async def add(value: int, amount: int = 1):
        return value + amount

    plugin = Plugin(
        "test",
        (
            entry_from(add, provider="test"),
            RegistryEntry(
                Id("dev.test:commands/add"),
                "command",
                {
                    "help": "增加数值",
                    "operation": "dev.test:operations/add",
                    "arguments": [
                        {"name": "value", "type": "integer"},
                        {"name": "amount", "type": "integer", "option": True},
                    ],
                },
                "test",
                register_to=Id("org.aurora.cli:registries/commands"),
            ),
        ),
    )
    output = StringIO()
    asyncio.run(
        run_cli(
            ["--data-dir", str(tmp_path), "--namespace", "dev.test", "add", "2", "--amount", "3"],
            plugins=[plugin],
            output=output,
        )
    )
    assert json.loads(output.getvalue()) == 5


def test_run_applies_config_before_prepare_and_flushes_stop(tmp_path):
    async def scenario():
        started = asyncio.Event()
        observations = []

        def factory(*, registry, ctx, hooks, storage, workspace_root):
            logging.getLogger(__name__).info("装配工厂日志")

            @hook_handler("dev.test:handlers/prepare", slot=PREPARE)
            def prepare():
                logging.getLogger(__name__).info("准备阶段日志")
                observations.append(ctx.get(Id(CONFIG)))

            @hook_handler("dev.test:handlers/start", slot=START)
            def start():
                logging.getLogger(__name__).info("启动阶段日志")
                started.set()

            @hook_handler("dev.test:handlers/stop", slot=STOP)
            def stop():
                logging.getLogger(__name__).info("停止阶段日志")
                ctx.set(Id(CONFIG), {"stopped": True})
                storage.set("dev.test", "finished", True)

            for phase, callback in ((PREPARE, prepare), (START, start), (STOP, stop)):
                entry = entry_from(callback, provider="test")
                registry.register(entry)
                hooks.connect(phase, entry.id, slot_instance="app", handler_instance="app")
            return [LifecycleComponent("app")]

        plugin = Plugin("test", (RegistryEntry(Id("dev.test:assemblies/app"), "assembly", factory, "test"),))
        await run_cli(["--data-dir", str(tmp_path), "ctx/set", CONFIG, '{"old":true}'], output=StringIO())
        task = asyncio.create_task(
            run_cli(
                ["--data-dir", str(tmp_path), "--config", '{"new":true}', "run", "dev.test:assemblies/app"],
                plugins=[plugin],
            )
        )
        await asyncio.wait_for(started.wait(), timeout=2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert observations == [{"new": True}]
        content = (tmp_path / "logs" / "aurora.log").read_text(encoding="utf-8")
        for message in ("装配工厂日志", "准备阶段日志", "启动阶段日志", "停止阶段日志"):
            assert content.count(message) == 1
        output = StringIO()
        await run_cli(["--data-dir", str(tmp_path), "ctx/get", CONFIG], output=output)
        assert json.loads(output.getvalue()) == {}

    asyncio.run(scenario())


@pytest.mark.parametrize("fault", ["", "stop", "flush"])
def test_real_cli_interrupt_and_shutdown_status(tmp_path, fault):
    metadata = tmp_path / "cli_shutdown_fixture-0.0.0.dist-info"
    metadata.mkdir()
    (metadata / "METADATA").write_text("Metadata-Version: 2.1\nName: cli-shutdown-fixture\nVersion: 0.0.0\n")
    (metadata / "entry_points.txt").write_text("[aurora.plugins]\ncli_shutdown_fixture = cli_shutdown_plugin:plugin\n")
    env = dict(os.environ)
    fixtures = Path(__file__).resolve().parents[1] / "fixtures"
    env["PYTHONPATH"] = os.pathsep.join([str(tmp_path), str(fixtures)])
    env["PYTHONIOENCODING"] = "utf-8"
    env["AURORA_CLI_SHUTDOWN_FAULT"] = fault
    data = tmp_path / "data"

    def run(*args):
        return subprocess.run(
            [sys.executable, "-m", "aurora_cli", "--plugin", "cli_shutdown_fixture", "--data-dir", str(data), *args],
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
            timeout=15,
        )

    initial = run("ctx/set", "dev.cli_shutdown:state/value", '"baseline"')
    assert initial.returncode == 0, initial.stderr
    snapshot = data / "framework" / "ctx.json"
    before = snapshot.read_bytes()
    result = run(
        "--assembly", "dev.cli_shutdown:assemblies/watch", "ctx/watch", "--key", "dev.cli_shutdown:state/value"
    )
    assert result.returncode == (1 if fault else 130), result.stderr
    events = [json.loads(line) for line in result.stdout.splitlines()]
    assert [event["value"] for event in events] == ["first", "second"]
    assert events[1]["revision"] == events[0]["revision"] + 1
    if fault:
        assert "故障" in result.stderr
    if fault == "flush":
        assert snapshot.read_bytes() == before
    if not fault:
        trace = (data / "namespaces" / "ns-dev.cli_shutdown" / "events.txt").read_text(encoding="utf-8").splitlines()
        assert trace == ["first", "second", "gate:closed", "stopped", "source:closed"]
        restored = run("ctx/get", "dev.cli_shutdown:state/value")
        assert restored.returncode == 0, restored.stderr
        assert json.loads(restored.stdout) == "stopped"

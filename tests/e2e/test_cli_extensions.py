"""验证命令包独立发现、执行绑定与运行需求。"""

import asyncio
import json
from importlib.metadata import EntryPoint
from io import StringIO

import pytest
from aurora_cli import commands
from aurora_cli.commander import run_cli
from aurora_cli.declarations import command_plugin
from aurora_core import Id
from aurora_core.discovery import ENTRY_POINT_GROUP
from aurora_core.invocation import invoke_operation


def test_directory_package_is_discovered_without_dispatcher_changes(tmp_path, monkeypatch):
    package = tmp_path / "self_contained_example"
    package.mkdir()
    entry = package / "__init__.py"
    entry.write_text(
        "from aurora_cli.declarations import command_plugin\n"
        "def execute(context, name):\n"
        '    print("你好 " + name, file=context.output)\n'
        "    return 7\n"
        "def plugin():\n"
        '    return command_plugin(__name__, {"hello": {"help": "独立命令", "executor": execute,'
        ' "arguments": [{"name": "name"}]}})\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(commands, "__path__", [str(tmp_path)])
    output = StringIO()
    assert asyncio.run(run_cli(["hello", "Aurora"], output=output)) == 7
    assert output.getvalue() == "你好 Aurora\n"
    output = StringIO()
    asyncio.run(run_cli(["--help"], output=output))
    assert "hello" in output.getvalue()
    assert "about" not in output.getvalue()
    entry.unlink()
    output = StringIO()
    asyncio.run(run_cli([], output=output))
    assert "hello" not in output.getvalue()
    with pytest.raises(SystemExit) as error:
        asyncio.run(run_cli(["hello", "Aurora"], output=StringIO()))
    assert error.value.code == 2


def test_runtime_executor_writes_transient_configuration_without_id_special_case(tmp_path):
    async def execute(context, value):
        await invoke_operation(
            context.registry, Id("org.aurora.core:operations/ctx/set"), Id("org.aurora.cli:state/config"), value
        )
        print("已写入", file=context.output)
        return 3

    plugin = command_plugin(
        "test.runtime",
        {
            "remember": {
                "help": "写入状态",
                "runtime": True,
                "executor": execute,
                "arguments": [{"name": "value", "type": "json"}],
            }
        },
        namespace="dev.test",
    )
    output = StringIO()
    assert (
        asyncio.run(
            run_cli(
                ["--data-dir", str(tmp_path), "dev.test:commands/remember", '{"value":42}'],
                plugins=[plugin],
                output=output,
            )
        )
        == 3
    )
    assert output.getvalue() == "已写入\n"
    output = StringIO()
    asyncio.run(run_cli(["--data-dir", str(tmp_path), "ctx/get", "org.aurora.cli:state/config"], output=output))
    assert json.loads(output.getvalue()) == {}


def test_entry_point_command_is_only_loaded_when_enabled(tmp_path, monkeypatch):
    (tmp_path / "cli_entry_example.py").write_text(
        "from aurora_core.discovery import Plugin\n"
        "from aurora_core.registry import RegistryEntry\n"
        "from aurora_core import Id\n"
        "def execute(context):\n"
        '    print("external", file=context.output)\n'
        "def plugin():\n"
        '    return Plugin("external", (RegistryEntry(Id("dev.test:commands/external"), "command",'
        ' {"help": "外部命令", "executor": execute}, "external",'
        ' register_to=Id("org.aurora.cli:registries/commands")),))\n',
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    point = EntryPoint(name="external", value="cli_entry_example:plugin", group=ENTRY_POINT_GROUP)
    monkeypatch.setattr("aurora_core.discovery.entry_points", lambda **kwargs: (point,))
    output = StringIO()
    asyncio.run(run_cli(["--help"], output=output))
    assert "dev.test:commands/external" not in output.getvalue()
    output = StringIO()
    assert asyncio.run(run_cli(["--plugin", "external", "dev.test:commands/external"], output=output)) == 0
    assert output.getvalue() == "external\n"


def test_duplicate_command_id_fails_before_execution():
    executed = []
    plugin = command_plugin(
        "conflicting", {"about": {"help": "重复", "executor": lambda context: executed.append(True)}}
    )
    with pytest.raises(ValueError, match="重复"):
        asyncio.run(run_cli(["about"], plugins=[plugin], output=StringIO()))
    assert executed == []

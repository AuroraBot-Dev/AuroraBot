"""验证定义目录包含 core、命令与显式插件，不执行登记目标。"""

import asyncio
from io import StringIO

import pytest
from aurora_cli.commander import run_cli
from aurora_core import Id
from aurora_core.discovery import Plugin
from aurora_core.registry import RegistryEntry


@pytest.mark.parametrize("command", [["id/list"], ["id", "list"]])
def test_list_definitions_without_starting_host(tmp_path, command, monkeypatch):
    monkeypatch.setenv("COLUMNS", "160")
    executed = []
    plugin = Plugin(
        "id_fixture",
        (RegistryEntry(Id("dev.test:operations/demo"), "operation", lambda: executed.append(True), "id_fixture"),),
    )
    output = StringIO()
    assert (
        asyncio.run(run_cli(["--data-dir", str(tmp_path / "unused"), *command], plugins=[plugin], output=output)) == 0
    )
    rendered = output.getvalue()
    assert "dev.test:operations/demo" in rendered
    assert "operation" in rendered
    assert "id_fixture" in rendered
    assert "org.aurora.core:registries/registries" in rendered
    assert "org.aurora.cli:commands/id/list" in rendered
    assert rendered.index("dev.test:operations/demo") < rendered.index("org.aurora.cli:commands/id/list")
    assert executed == []
    assert not (tmp_path / "unused").exists()

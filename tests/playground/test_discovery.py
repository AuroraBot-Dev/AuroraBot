from __future__ import annotations

import json
from textwrap import dedent
from typing import TYPE_CHECKING

import pytest

from aurora_kernel import Host
from aurora_kernel.discovery import PackageSource, StaticSource
from playground.discovery import module_spec
from playground.protocol import Empty, Module, Operation
from playground.session import Session

if TYPE_CHECKING:
    from pathlib import Path

    from aurora_kernel.lifecycle import ManagedAssembly


def test_package_discovers_new_playground_without_session_registration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package = tmp_path / "discovered_playgrounds"
    child = package / "echo"
    child.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (child / "__init__.py").write_text(
        dedent("""\
            from playground.protocol import Module, Model, Operation

            class Text(Model):
                text: str

            def echo(*, text: str) -> Text:
                return Text(text=text)

            def create() -> tuple[Operation, ...]:
                return (Operation("echo", "返回文本", Text, Text, echo, {"text": "你好"}),)

            MODULE = Module("echo", "自动发现的模块", create)
        """),
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    source = PackageSource("discovered_playgrounds", extract=module_spec, entry_module=None)
    session = Session((source,))
    assert session.handle('{"action":"list"}')["result"]["modules"] == [
        {"module": "echo", "description": "自动发现的模块"}
    ]
    response = session.handle('{"module":"echo","operation":"echo","input":{"text":"你好"}}')
    assert response["result"] == {"text": "你好"}


def test_duplicate_modules_fail_before_any_operation_factory_runs() -> None:
    created: list[str] = []

    def create() -> tuple[Operation, ...]:
        created.append("created")
        return ()

    module = Module("duplicate", "重复模块", create)
    with pytest.raises(ValueError, match="名称重复"):
        Session((StaticSource((module, module)),))
    assert not created
    with pytest.raises(TypeError, match="MODULE"):
        Session((StaticSource((object(),)),))


def test_duplicate_operations_are_rejected_without_executing_handlers() -> None:
    effects: list[str] = []

    def execute() -> Empty:
        effects.append("called")
        return Empty()

    operation = Operation("same", "重复操作", Empty, Empty, execute, {})
    module = Module("duplicate", "重复操作", lambda: (operation, operation))
    session = Session((StaticSource((module,)),))
    assert session.handle('{"action":"list"}')["ok"]
    response = session.handle('{"module":"duplicate","operation":"same"}')
    assert response["error"]["code"] == "invalid_module"
    assert not effects


def test_discovery_description_and_bad_input_do_not_build_kernel(monkeypatch: pytest.MonkeyPatch) -> None:
    built: list[Host] = []
    original = Host.prepare

    async def prepare(host: Host) -> ManagedAssembly:
        built.append(host)
        return await original(host)

    monkeypatch.setattr(Host, "prepare", prepare)
    session = Session()
    assert session.handle('{"action":"list"}')["ok"]
    assert session.handle('{"action":"describe","module":"kernel"}')["ok"]
    request = {"module": "kernel", "operation": "increment", "input": {"amount": "bad"}}
    assert not session.handle(json.dumps(request))["ok"]
    assert not built
    response = session.handle('{"module":"kernel","operation":"increment"}')
    assert response["result"] == {"value": 2}
    assert len(built) == 1
    session.close()

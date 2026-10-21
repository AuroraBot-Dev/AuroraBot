from __future__ import annotations

import asyncio
import json
import sys
import threading
from io import StringIO
from types import SimpleNamespace

import pytest
from textual.widgets import Select

from aurora_kernel.discovery import StaticSource
from playground import __main__ as entry
from playground.protocol import Empty, Module, Operation
from playground.session import Session
from playground.tui import PlaygroundApp


def test_editor_validation_module_switching_and_state() -> None:
    async def scenario() -> None:
        app = PlaygroundApp(module="kernel")
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            assert json.loads(app.input_editor.text) == {"amount": 3}
            assert "input_schema" in json.loads(app.schema_editor.text)
            assert app.output_editor.text == "尚未执行操作。"
            assert await pilot.click("#execute")
            await app.workers.wait_for_complete()
            assert json.loads(app.output_editor.text)["result"] == {"value": 6}
            for invalid, code in [("{", "invalid_json"), ('{"amount":"3"}', "invalid_input")]:
                app.input_editor.load_text(invalid)
                await pilot.press("f5")
                await app.workers.wait_for_complete()
                assert json.loads(app.output_editor.text)["error"]["code"] == code
            await pilot.press("ctrl+r")
            assert json.loads(app.input_editor.text) == {"amount": 3}
            app.operation_select.value = Select.NULL
            await pilot.pause()
            assert app.execute_button.disabled
            app.module_select.value = "cli"
            await pilot.pause()
            assert app.operation_select.value == "execute"
            app.module_select.value = "kernel"
            await pilot.pause()
            assert not app.execute_button.disabled
            app.input_editor.load_text('{"amount":0}')
            await pilot.press("f5")
            await app.workers.wait_for_complete()
            assert json.loads(app.output_editor.text)["result"] == {"value": 6}
        assert app.backend.closed and app.backend.session.closed

    asyncio.run(scenario())


def test_slow_async_operation_keeps_ui_responsive_and_closes_on_its_thread() -> None:
    async def scenario() -> None:
        ui_loop = asyncio.get_running_loop()
        started = asyncio.Event()
        released = threading.Event()
        calls: list[tuple[int, asyncio.AbstractEventLoop]] = []
        closed: list[int] = []
        background_tasks: list[asyncio.Task[None]] = []

        async def background() -> None:
            try:
                await asyncio.Event().wait()
            finally:
                closed.append(threading.get_ident())

        async def execute() -> Empty:
            calls.append((threading.get_ident(), asyncio.get_running_loop()))
            if len(calls) == 1:
                background_tasks.append(asyncio.create_task(background()))
            ui_loop.call_soon_threadsafe(started.set)
            await asyncio.to_thread(released.wait)
            return Empty()

        operation = Operation("execute", "等待测试信号", Empty, Empty, execute, {})
        session = Session((StaticSource((Module("fake", "测试模块", lambda: (operation,)),)),))
        app = PlaygroundApp(session=session)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.action_execute()
            try:
                await asyncio.wait_for(started.wait(), timeout=3)
                assert app.execute_button.disabled and app.module_select.disabled
                await pilot.press("tab")
                app.action_execute()
                assert len(calls) == 1
            finally:
                released.set()
            await app.workers.wait_for_complete()
            assert json.loads(app.output_editor.text)["ok"]
            app.action_execute()
            await app.workers.wait_for_complete()
        first, second = calls
        assert first == second
        assert calls[0][0] != threading.get_ident() and calls[0][1] is not ui_loop
        assert closed == [calls[0][0]]
        assert session.closed

    asyncio.run(scenario())


def test_empty_module_disables_execution() -> None:
    async def scenario() -> None:
        session = Session((StaticSource((Module("empty", "无操作", lambda: ()),)),))
        app = PlaygroundApp(session=session)
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.execute_button.disabled and app.operation_select.disabled
            app.action_execute()
            assert app.output_editor.text == "尚未执行操作。"

    asyncio.run(scenario())


def test_tui_entry_requires_terminal_and_forwards_module(monkeypatch: pytest.MonkeyPatch) -> None:
    class Terminal(StringIO):
        def isatty(self) -> bool:
            return True

    selected: list[str] = []

    def run(*, module: str) -> int:
        selected.append(module)
        return 0

    monkeypatch.setattr(sys, "argv", ["playground", "--tui", "--module", "kernel"])
    monkeypatch.setattr(sys, "stdin", StringIO())
    with pytest.raises(SystemExit, match="2"):
        entry.main()
    monkeypatch.setattr(sys, "stdin", Terminal())
    monkeypatch.setattr(sys, "stdout", Terminal())
    monkeypatch.setattr(entry, "import_module", lambda name: SimpleNamespace(run=run))
    assert entry.main() == 0
    assert selected == ["kernel"]

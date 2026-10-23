from __future__ import annotations

import asyncio
import json
import sys
from io import StringIO

import pytest
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput

from aurora_cli.utils.process import EXIT_CONFIG_ERROR
from playground.__main__ import main
from playground.commands import Commands
from playground.rendering import write_response
from playground.session import Session
from playground.terminal import create_editor


def test_shortcuts_share_state_and_validation_with_json_requests() -> None:
    commands = Commands(Session())
    assert commands.handle("use kernel")["ok"]
    assert commands.handle("describe increment")["result"]["operations"][0]["operation"] == "increment"
    assert commands.handle('increment {"amount":3}')["result"] == {"value": 6}
    assert commands.handle('{"module":"kernel","operation":"increment"}')["result"] == {"value": 8}
    assert not commands.handle("use absent")["ok"]
    assert commands.module == "kernel"
    before = commands.handle("state")
    assert commands.handle('increment {"amount":"2"}')["error"]["code"] == "invalid_input"
    assert commands.handle('increment {"amount":1e9999}')["error"]["code"] == "invalid_command"
    assert commands.handle("state") == before
    assert commands.handle('cli.demo {"argv":["demo","greet","小极光"]}')["result"]["result"] == {
        "name": "小极光",
        "message": "你好，小极光！",
    }


@pytest.mark.parametrize("pretty", [False, True])
def test_main_formats_json_and_selects_initial_module(monkeypatch: pytest.MonkeyPatch, *, pretty: bool) -> None:
    stdout, stderr = StringIO(), StringIO()
    monkeypatch.setattr(sys, "argv", ["playground", "--module", "kernel", *([] if pretty else ["--no-pretty"])])
    monkeypatch.setattr(sys, "stdin", StringIO('increment {"amount":3}\n'))
    monkeypatch.setattr(sys, "stdout", stdout)
    monkeypatch.setattr(sys, "stderr", stderr)
    assert main() == 0
    output = stdout.getvalue()
    assert json.loads(output) == {"ok": True, "module": "kernel", "operation": "increment", "result": {"value": 6}}
    assert ('\n  "ok"' in output) is pretty
    assert stderr.getvalue() == ""


def test_invalid_initial_module_does_not_execute_input(monkeypatch: pytest.MonkeyPatch) -> None:
    stdin, stdout = StringIO('kernel.increment {"amount":3}\n'), StringIO()
    monkeypatch.setattr(sys, "argv", ["playground", "--module", "absent"])
    monkeypatch.setattr(sys, "stdin", stdin)
    monkeypatch.setattr(sys, "stdout", stdout)
    assert main() == EXIT_CONFIG_ERROR
    assert not json.loads(stdout.getvalue())["ok"]
    assert stdin.tell() == 0


def test_editor_multiline_history_and_completion() -> None:
    async def scenario() -> None:
        commands = Commands(Session())
        commands.handle("use kernel")
        with create_pipe_input() as pipe:
            editor = create_editor(commands, pipe, DummyOutput())
            pipe.send_text('increment {\r"amount": 3\r}\r')
            request = await asyncio.wait_for(editor.prompt_async(), timeout=3)
            assert commands.handle(request)["result"] == {"value": 6}
            pipe.send_text("\x1b[A\r")
            previous = await asyncio.wait_for(editor.prompt_async(), timeout=3)
            assert previous == request
            changed = asyncio.Event()
            editor.default_buffer.on_text_changed += lambda buffer: (
                changed.set() if buffer.text == "increment" else None
            )
            completing = asyncio.create_task(editor.prompt_async())
            pipe.send_text("incre\t")
            await asyncio.wait_for(changed.wait(), timeout=3)
            pipe.send_text("\r")
            completed = await asyncio.wait_for(completing, timeout=3)
            assert completed == "increment"
            # 括号出现在字符串中时，不应把完整请求误判为需要续行。
            pipe.send_text('cli.demo {"argv":["demo","greet","{"]}\r')
            quoted = await asyncio.wait_for(editor.prompt_async(), timeout=3)
            assert commands.handle(quoted)["ok"]

    asyncio.run(scenario())


@pytest.mark.parametrize("pretty", [True, False])
def test_terminal_color_and_compact_output(*, pretty: bool) -> None:
    class Terminal(StringIO):
        def isatty(self) -> bool:
            return True

    output = Terminal()
    write_response({"中文": True, "number": 3, "value": None}, output, pretty=pretty)
    rendered = output.getvalue()
    if pretty:
        assert "\x1b[" in rendered and rendered.count("\n") > 1
    else:
        assert "\x1b[" not in rendered
        assert rendered == '{"中文":true,"number":3,"value":null}\n'


def test_slash_commands_share_state_and_preserve_json_and_cli_arguments() -> None:
    with Session() as session:
        commands = Commands(session)
        assert commands.handle("/use kernel")["ok"]
        result = commands.handle('/increment {"amount":3}')["result"]
        assert result == {"value": 6}
        assert commands.handle("/kernel.state")["result"]["namespaces"]["counter"]["value"] == result["value"]
        assert commands.handle("/describe /kernel.increment")["ok"]
        assert commands.handle("/help")["result"]["commands"][0].startswith("/list")
        request = commands.request('/aurora config "带 空格"')
        assert request["input"] == {"argv": ["config", "带 空格"]}
        before = commands.handle("/state")
        assert "/kernel.increment" in commands.suggestions("/inc")
        assert "/use kernel" in commands.suggestions("/use k")
        assert "/describe kernel.increment" in commands.suggestions("/describe kernel.in")
        assert not commands.suggestions('/increment {"amount":')
        assert commands.handle("/state") == before
        assert commands.handle("/quit")["result"] == {"closed": True}


def test_slash_menu_opens_on_typing_and_confirms_without_executing() -> None:
    async def scenario() -> None:
        with Session() as session, create_pipe_input() as pipe:
            commands = Commands(session)
            commands.handle("/use kernel")
            editor = create_editor(commands, pipe, DummyOutput())
            visible = asyncio.Event()
            editor.default_buffer.on_completions_changed += lambda buffer: (
                visible.set() if buffer.complete_state and buffer.complete_state.completions else None
            )
            prompting = asyncio.create_task(editor.prompt_async())
            pipe.send_text("/inc")
            await asyncio.wait_for(visible.wait(), timeout=3)
            assert not prompting.done()
            assert commands.handle("/state")["result"]["namespaces"]["counter"]["value"] == 0
            pipe.send_text("\x1b[B\x1b[B\t\r")
            completed = await asyncio.wait_for(prompting, timeout=3)
            assert completed == "/kernel.increment"
            assert commands.handle(completed)["result"] == {"value": 2}

    asyncio.run(scenario())

from __future__ import annotations

import json
import shlex
import subprocess
from typing import TYPE_CHECKING, Any

import pytest

from aurora_cli.utils.process import EXIT_CONFIG_ERROR
from playground.commands import Commands
from playground.modules import cli
from playground.session import Session
from tests.cli.plugin_support import write_plugin

if TYPE_CHECKING:
    from pathlib import Path


def test_real_cli_uses_project_config_and_local_plugin(tmp_path: Path) -> None:
    write_plugin(tmp_path)
    with Session() as session:
        commands = Commands(session)
        prefix = shlex.join(["aurora", "--root", str(tmp_path)])
        initialized = commands.handle(f"{prefix} config extra --init")
        assert initialized["ok"] and initialized["result"]["exit_code"] == 0
        assert (tmp_path / "settings/custom.toml").is_file()
        edited = commands.handle(f'{prefix} config extra --set "extra.message=真实配置"')
        assert edited["result"]["exit_code"] == 0
        called = commands.handle(f"{prefix} greet")
        assert called["result"]["stdout"].strip() == "真实配置 1"
        missing = commands.handle(f"{prefix} config extra --missing")
        assert missing["result"]["result"] == {}
        bad = commands.handle(f"{prefix} missing-command")
        assert bad["ok"] and bad["result"]["exit_code"] == EXIT_CONFIG_ERROR
        assert bad["result"]["stderr"]
        assert commands.handle("kernel.increment")["result"] == {"value": 2}


@pytest.mark.parametrize(
    "inputs",
    [
        {},
        {"argv": [], "command": "aurora"},
        {"command": ""},
        {"command": 'aurora "'},
        {"argv": [], "timeout_seconds": 0},
    ],
)
def test_invalid_cli_input_never_starts_a_process(monkeypatch: pytest.MonkeyPatch, inputs: dict[str, Any]) -> None:
    def unexpected(*args: Any, **kwargs: Any) -> None:
        pytest.fail("无效参数不能启动进程")

    monkeypatch.setattr(cli.subprocess, "run", unexpected)
    with Session() as session:
        response = session.handle(json.dumps({"module": "cli", "operation": "execute", "input": inputs}))
    assert response["error"]["code"] == "invalid_input"


def test_cli_keeps_arguments_stdin_and_timeout_without_shell_or_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[list[str], dict[str, Any]]] = []

    def run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append((argv, kwargs))
        if len(calls) == 1:
            return subprocess.CompletedProcess(argv, 0, '["真实输出"]\n', "诊断\n")
        raise subprocess.TimeoutExpired(argv, 1, output="部分输出".encode(), stderr=b"partial error")

    monkeypatch.setattr(cli.subprocess, "run", run)
    timeout_seconds = 7
    result = cli.execute(
        command='aurora config "含 空格" "$(literal)"', stdin="输入\n", timeout_seconds=timeout_seconds
    )
    argv, options = calls[0]
    assert argv[-3:] == ["config", "含 空格", "$(literal)"]
    assert options["input"] == "输入\n" and options["timeout"] == timeout_seconds
    assert options.get("shell", False) is False
    assert result.exit_code == 0 and result.result == ["真实输出"] and result.stderr == "诊断\n"
    timed_out = cli.execute(argv=["--version"], timeout_seconds=1)
    timeout_exit_code = 124
    assert timed_out.exit_code == timeout_exit_code and timed_out.timed_out
    assert timed_out.stdout == "部分输出" and timed_out.stderr == "partial error"
    first_call, timeout_call = calls
    assert first_call[0] == argv and timeout_call[0][-1] == "--version"

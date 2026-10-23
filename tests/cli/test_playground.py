from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from aurora_cli.commander import build_registry, run
from aurora_cli.commands import playground
from aurora_cli.utils.process import EXIT_CONFIG_ERROR

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("separator", [[], ["--"]])
def test_discovered_command_preserves_json_pipe_from_another_directory(tmp_path: Path, separator: list[str]) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "aurora_cli",
            "--root",
            str(ROOT),
            "playground",
            *separator,
            "--pretty",
            "--module",
            "kernel",
        ],
        cwd=tmp_path,
        input='increment {"amount":3}\n',
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert json.loads(result.stdout)["result"] == {"value": 6}
    assert '\n  "ok"' in result.stdout


@pytest.mark.parametrize("option", ["--help", "--unknown", "--tui"])
def test_playground_interprets_help_and_errors(option: str) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "aurora_cli", "playground", option],
        cwd=ROOT,
        input="",
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    if option == "--help":
        assert result.returncode == 0
        assert "--tui" in result.stdout and "--module" in result.stdout
    else:
        assert result.returncode == EXIT_CONFIG_ERROR
        assert result.stdout == ""
        assert "交互终端" in result.stderr if option == "--tui" else "--unknown" in result.stderr


def test_missing_source_reports_how_to_select_repository(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    registry = build_registry(((playground.COMMAND, playground.execute),))
    assert run(["--root", str(tmp_path), "playground"], registry=registry) == EXIT_CONFIG_ERROR
    output = capsys.readouterr()
    assert output.out == ""
    assert "源码仓库" in output.err and "--root" in output.err

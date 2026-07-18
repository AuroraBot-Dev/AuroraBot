from __future__ import annotations

import argparse
from typing import TYPE_CHECKING

from aurora.commands import check
from aurora.main import build_parser, run
from aurora.runtime import DEV

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def test_check_runs_all_groups_when_both_filters_are_set(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    commands: list[list[str]] = []

    def record(command: list[str], root: Path) -> int:
        assert root == tmp_path
        commands.append(command)
        return 0

    monkeypatch.setattr(check, "run_process", record)
    arguments = argparse.Namespace(root=tmp_path, lint=True, test=True, fix=False, unsafe_fixes=False)

    assert check.execute(arguments) == 0
    assert commands == [
        ["uv", "run", "ruff", "check", "aurora/", "src/", "tests/"],
        ["uv", "run", "ruff", "format", "--check", "aurora/", "src/", "tests/"],
        ["uv", "run", "pyright", "aurora/", "src/"],
        ["uv", "run", "pytest", "-v", "--cov=src", "--cov=aurora"],
    ]


def test_cli_defaults_to_dev_and_parses_only_once(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[tuple[Path, str | None, object]] = []

    def execute(arguments: argparse.Namespace) -> int:
        calls.append((arguments.root, arguments.profile, DEV))
        return 0

    monkeypatch.setattr("aurora.commands.dev.execute", execute)

    assert run(["--root", str(tmp_path), "--profile", "test"]) == 0
    assert calls == [(tmp_path, "test", DEV)]


def test_cli_registers_each_public_process_command() -> None:
    parser = build_parser()

    for command in ("dev", "run", "serve", "console", "check"):
        assert parser.parse_args([command]).command == command

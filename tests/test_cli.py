from __future__ import annotations

import argparse
from typing import TYPE_CHECKING

from scripts.cli import check, runtime

if TYPE_CHECKING:
    import pytest


def test_check_runs_all_groups_when_both_filters_are_set(monkeypatch: pytest.MonkeyPatch) -> None:
    commands: list[list[str]] = []

    def run(command: list[str]) -> int:
        commands.append(command)
        return 0

    monkeypatch.setattr(check, "run", run)

    assert check.check(argparse.Namespace(lint=True, test=True, fix=False, unsafe_fixes=False)) == 0
    assert commands == [
        ["uv", "run", "ruff", "check", "bot.py", "src/", "tests/", "scripts/"],
        ["uv", "run", "ruff", "format", "--check", "bot.py", "src/", "tests/", "scripts/"],
        ["uv", "run", "pyright", "bot.py", "src/", "scripts/"],
        ["uv", "run", "pytest", "-v", "--cov=src"],
    ]


def test_installed_runtime_command_calls_composition_entry_directly(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def record(argv: list[str]) -> None:
        calls.append(argv)

    monkeypatch.setattr("src.dashboard.cli.main", record)
    args = argparse.Namespace(root="C:/aurora", profile="production")

    assert runtime.serve(args) == 0
    assert calls == [["--root", "C:/aurora", "--profile", "production", "serve"]]

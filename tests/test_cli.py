from __future__ import annotations

import argparse
from typing import TYPE_CHECKING

import pytest

from aurora.commands import check
from aurora.main import build_parser, run

if TYPE_CHECKING:
    from pathlib import Path

_ARGPARSE_ERROR = 2


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


@pytest.mark.parametrize(
    ("flags", "expected"),
    (
        (["--headless"], frozenset()),
        (["--console"], frozenset({"console"})),
        (["--dashboard"], frozenset({"dashboard"})),
        (["--mcp"], frozenset({"mcp"})),
        (["--console", "--dashboard"], frozenset({"console", "dashboard"})),
        (["--console", "--mcp"], frozenset({"console", "mcp"})),
        (["--dashboard", "--mcp"], frozenset({"dashboard", "mcp"})),
        (["--console", "--dashboard", "--mcp"], frozenset({"console", "dashboard", "mcp"})),
    ),
)
def test_cli_passes_each_exact_platform_set_once(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    flags: list[str],
    expected: frozenset[str],
) -> None:
    calls: list[tuple[Path, str | None, frozenset[str] | None]] = []

    async def execute(root: Path, profile: str | None, platforms: frozenset[str] | None) -> None:
        calls.append((root, profile, platforms))

    monkeypatch.setattr("aurora.runtime.run_runtime", execute)

    assert run(["--root", str(tmp_path), "--profile", "test", *flags]) == 0
    assert calls == [(tmp_path, "test", expected)]


def test_cli_uses_preference_selection_when_no_platform_flag_is_present(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[frozenset[str] | None] = []

    async def execute(_root: Path, _profile: str | None, platforms: frozenset[str] | None) -> None:
        calls.append(platforms)

    monkeypatch.setattr("aurora.runtime.run_runtime", execute)

    assert run(["--root", str(tmp_path)]) == 0
    assert calls == [None]


@pytest.mark.parametrize("platform", ("--console", "--dashboard", "--mcp"))
def test_headless_rejects_positive_platform_flags(platform: str) -> None:
    with pytest.raises(SystemExit) as raised:
        run(["--headless", platform])

    assert raised.value.code == _ARGPARSE_ERROR


@pytest.mark.parametrize("command", ("dev", "run", "serve", "console"))
def test_cli_rejects_removed_runtime_commands(command: str) -> None:
    with pytest.raises(SystemExit) as raised:
        run([command])

    assert raised.value.code == _ARGPARSE_ERROR


def test_check_does_not_enter_runtime_composition(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    commands: list[list[str]] = []

    async def fail_runtime(_root: Path, _profile: str | None, _platforms: frozenset[str] | None) -> None:
        pytest.fail("check loaded the runtime composition")

    monkeypatch.setattr("aurora.runtime.run_runtime", fail_runtime)
    monkeypatch.setattr(check, "run_process", lambda command, _root: commands.append(command) or 0)

    assert run(["--root", str(tmp_path), "check", "--lint"]) == 0
    assert commands == [
        ["uv", "run", "ruff", "check", "aurora/", "src/", "tests/"],
        ["uv", "run", "ruff", "format", "--check", "aurora/", "src/", "tests/"],
        ["uv", "run", "pyright", "aurora/", "src/"],
    ]


def test_cli_registers_only_the_public_quality_command() -> None:
    parser = build_parser()

    assert parser.parse_args(["check"]).command == "check"

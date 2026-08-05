# ruff: noqa: PLR2004, FBT001
from __future__ import annotations

import argparse
from typing import TYPE_CHECKING

import pytest

from aurora.commands import check
from aurora.main import build_parser, run

if TYPE_CHECKING:
    from pathlib import Path


def test_check_runs_all_groups_when_both_filters_are_set(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    commands: list[list[str]] = []

    def record(command: list[str], root: Path) -> int:
        assert root == tmp_path
        commands.append(command)
        return 0

    monkeypatch.setattr(check, "run_process", record)
    arguments = argparse.Namespace(root=tmp_path, lint=True, test=True, fix=False, unsafe_fixes=False, check=False)

    assert check.execute(arguments) == 0
    assert commands[-1] == ["uv", "run", "--no-sync", "pytest", "-v", "--cov=src", "--cov=aurora"]


@pytest.mark.parametrize(
    ("flags", "expected_platforms", "expected_headless"),
    (
        (["--headless"], None, True),
        (["--platform", "dashboard"], frozenset({"dashboard"}), False),
        (["--platform", "mcp"], frozenset({"mcp"}), False),
        (["--platform", "dashboard", "--platform", "mcp"], frozenset({"dashboard", "mcp"}), False),
        (["--headless", "--platform", "dashboard"], frozenset({"dashboard"}), True),
        (["--headless", "--platform", "dashboard", "--platform", "mcp"], frozenset({"dashboard", "mcp"}), True),
    ),
)
def test_cli_passes_each_exact_platform_set_once(
    monkeypatch: pytest.MonkeyPatch,
    flags: list[str],
    expected_platforms: frozenset[str] | None,
    expected_headless: bool,
) -> None:
    calls: list[tuple[frozenset[str] | None, bool]] = []

    async def execute(platforms: frozenset[str] | None, *, headless: bool = False) -> None:
        calls.append((platforms, headless))

    monkeypatch.setattr("aurora.runtime.run_runtime", execute)
    assert run(flags) == 0
    assert calls == [(expected_platforms, expected_headless)]


def test_cli_uses_preference_selection_when_no_platform_flag_is_present(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[frozenset[str] | None] = []

    async def execute(platforms: frozenset[str] | None, *, headless: bool = False) -> None:  # noqa: ARG001
        calls.append(platforms)

    monkeypatch.setattr("aurora.runtime.run_runtime", execute)
    assert run([]) == 0
    assert calls == [None]


@pytest.mark.parametrize("platform", ("unknown", "console,mcp"))
def test_cli_rejects_unknown_platform_names(platform: str) -> None:
    with pytest.raises(SystemExit) as raised:
        run(["--platform", platform])
    assert raised.value.code == 2


def test_check_does_not_enter_runtime_composition(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    commands: list[list[str]] = []

    async def fail_runtime(_platforms: frozenset[str] | None, *, headless: bool = False) -> None:  # noqa: ARG001
        pytest.fail("check loaded runtime composition")

    monkeypatch.setattr("aurora.runtime.run_runtime", fail_runtime)
    monkeypatch.setattr(check, "run_process", lambda command, _root: commands.append(command) or 0)
    assert run(["--root", str(tmp_path), "check", "--lint"]) == 0
    assert len(commands) == 3


def test_cli_registers_only_the_public_quality_command() -> None:
    parser = build_parser()
    assert parser.parse_args([]).profile is None
    assert parser.parse_args(["check"]).command == "check"

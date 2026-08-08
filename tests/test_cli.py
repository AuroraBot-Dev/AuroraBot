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
    assert run(["start", *flags]) == 0
    assert calls == [(expected_platforms, expected_headless)]


def test_cli_uses_preference_selection_when_no_platform_flag_is_present(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[frozenset[str] | None] = []

    async def execute(platforms: frozenset[str] | None, *, headless: bool = False) -> None:  # noqa: ARG001
        calls.append(platforms)

    monkeypatch.setattr("aurora.runtime.run_runtime", execute)
    assert run(["start"]) == 0
    assert calls == [None]


@pytest.mark.parametrize("platform", ("unknown", "console,mcp"))
def test_cli_rejects_unknown_platform_names(platform: str) -> None:
    with pytest.raises(SystemExit) as raised:
        run(["start", "--platform", platform])
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
    assert parser.parse_args(["check"]).command == "check"
    assert parser.parse_args(["start"]).command == "start"


def test_cli_without_command_shows_usage_only() -> None:
    with pytest.raises(SystemExit) as raised:
        build_parser().parse_args([])
    assert raised.value.code == 2


def test_cli_without_command_does_not_start_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    async def execute(platforms: frozenset[str] | None, *, headless: bool = False) -> None:  # noqa: ARG001
        pytest.fail("bare aurora entered runtime composition")

    monkeypatch.setattr("aurora.runtime.run_runtime", execute)
    with pytest.raises(SystemExit) as raised:
        run([])
    assert raised.value.code == 2


def test_start_initializes_config_with_root_and_profile(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    init_calls: list[tuple[Path, str | None]] = []

    async def run_runtime(_platforms: object, **_kwargs: object) -> None:
        return None

    monkeypatch.setattr("aurora.runtime.run_runtime", run_runtime)
    monkeypatch.setattr(
        "aurora.commands.start.init_config",
        lambda root, profile: init_calls.append((root, profile)),
    )
    assert run(["--root", str(tmp_path), "--profile", "dev", "start"]) == 0
    assert init_calls == [(tmp_path, "dev")]


def test_check_and_donk_do_not_initialize_config(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_if_called(*_args: object) -> None:
        pytest.fail("config initialized for non-runtime command")

    monkeypatch.setattr("aurora.commands.start.init_config", fail_if_called)
    monkeypatch.setattr("aurora.commands.check.run_process", lambda _command, _root: 0)
    monkeypatch.setattr("aurora.commands.donk._invoke", lambda *_args: 0)
    assert run(["check", "--lint"]) == 0
    assert run(["donk", "show"]) == 0

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING

from aurora.commands import about, check
from aurora.main import build_parser, run

if TYPE_CHECKING:
    import pytest

FAILED_EXIT_CODE = 3
EXPECTED_COMMAND_CALLS = 2


def test_bare_cli_and_about_are_non_effectful() -> None:
    assert run([]) == 0
    assert run(["about"]) == 0


def test_each_command_registers_its_own_executor() -> None:
    parser = build_parser()

    about_arguments = parser.parse_args([about.NAME])
    check_arguments = parser.parse_args([check.NAME])

    assert about_arguments.executor is about.execute
    assert check_arguments.executor is check.execute


def test_check_command_stops_at_first_failed_stage(monkeypatch: pytest.MonkeyPatch) -> None:
    return_codes = iter((0, FAILED_EXIT_CODE))
    calls: list[tuple[str, ...]] = []

    def fake_run(command: tuple[str, ...], **_kwargs: object) -> SimpleNamespace:
        calls.append(command)
        return SimpleNamespace(returncode=next(return_codes))

    monkeypatch.setattr(check.subprocess, "run", fake_run)

    assert check.execute(build_parser().parse_args([check.NAME])) == FAILED_EXIT_CODE
    assert len(calls) == EXPECTED_COMMAND_CALLS

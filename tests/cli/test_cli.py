from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

import pytest

from aurora_cli.commander import build_registry
from aurora_cli.commander import run as _run
from aurora_cli.commands import CommandSpec, about, check, docs
from aurora_cli.utils.process import EXIT_FAILURE, EXIT_INTERRUPTED, run_process
from tests.cli.support import EXPECTED_LINT_COMMANDS, FAILED_EXIT_CODE, build_parser

if TYPE_CHECKING:
    from pathlib import Path


def test_check_command_runs_all_selected_stages_and_summarizes_failures(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    return_codes = iter((0, FAILED_EXIT_CODE, 0))
    calls: list[tuple[str, ...]] = []

    def fake_run(command: tuple[str, ...], _root: Path) -> int:
        calls.append(command)
        return next(return_codes)

    monkeypatch.setattr(check, "run_process", fake_run)
    arguments = build_parser().parse_args([check.COMMAND["name"], "--lint"])

    assert check.execute(arguments) == EXIT_FAILURE
    assert len(calls) == EXPECTED_LINT_COMMANDS
    assert "1 项检查失败" in capsys.readouterr().err


def test_check_fix_flags_and_test_selection(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, ...]] = []

    def fake_run(command: tuple[str, ...], _root: Path) -> int:
        calls.append(command)
        return 0

    monkeypatch.setattr(check, "run_process", fake_run)
    parser = build_parser()

    assert check.execute(parser.parse_args([check.COMMAND["name"], "--lint", "--fix", "--unsafe-fixes"])) == 0
    assert "--fix" in calls[0]
    assert "--unsafe-fixes" in calls[0]
    assert "--check" not in calls[1]

    calls.clear()
    assert check.execute(parser.parse_args([check.COMMAND["name"], "--test"])) == 0
    assert len(calls) == 1
    assert "pytest" in calls[0]
    assert "--cov" not in calls[0]

    calls.clear()
    assert check.execute(parser.parse_args([check.COMMAND["name"], "--test", "--coverage"])) == 0
    assert len(calls) == 1
    assert "--cov" in calls[0]


def test_process_boundary_reports_failure_and_interrupt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class Result:
        returncode = FAILED_EXIT_CODE

    monkeypatch.setattr("aurora_cli.utils.process.subprocess.run", lambda *_args, **_kwargs: Result())
    assert run_process(("example",), tmp_path) == FAILED_EXIT_CODE
    assert "命令失败" in capsys.readouterr().err

    def interrupt(*_args: object, **_kwargs: object) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr("aurora_cli.utils.process.subprocess.run", interrupt)
    assert run_process(("example",), tmp_path) == EXIT_INTERRUPTED


def test_commander_runs_a_custom_registry(capsys: pytest.CaptureFixture[str]) -> None:
    registry = build_registry(((about.COMMAND, about.execute),))

    assert _run(["about"], registry=registry) == 0
    assert "AuroraBot" in capsys.readouterr().out


def test_commander_rejects_duplicate_command_names() -> None:
    with pytest.raises(ValueError, match="命令重复注册"):
        build_registry(((about.COMMAND, about.execute), (about.COMMAND, about.execute)))


def test_commander_rejects_unknown_spec_fields_and_empty_names() -> None:
    with pytest.raises(ValueError, match="未知字段"):
        build_registry(((cast("CommandSpec", {**about.COMMAND, "surprise": 1}), about.execute),))
    with pytest.raises(ValueError, match="命令名称不能为空"):
        build_registry(((cast("CommandSpec", {"name": "  "}), about.execute),))


def test_commander_rejects_non_callable_executor() -> None:
    with pytest.raises(ValueError, match="必须绑定可调用执行器"):
        build_registry(((about.COMMAND, cast("Any", "not-callable")),))


def test_commander_validates_positional_arg_specs() -> None:
    with pytest.raises(ValueError, match="位置参数必须是帮助文本或 add_argument 字典"):
        build_registry(((cast("CommandSpec", {**about.COMMAND, "args": {"target": 1}}), about.execute),))
    with pytest.raises(ValueError, match="位置参数帮助文本不能为空"):
        build_registry(((cast("CommandSpec", {**about.COMMAND, "args": {"target": "  "}}), about.execute),))


def test_commander_rejects_empty_passthrough_help() -> None:
    with pytest.raises(ValueError, match="透传参数帮助文本不能为空"):
        build_registry(((cast("CommandSpec", {**docs.COMMAND, "passthrough": "  "}), docs.execute),))

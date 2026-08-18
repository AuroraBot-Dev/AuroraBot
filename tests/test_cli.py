from __future__ import annotations

from typing import TYPE_CHECKING

from aurora.commands import about, check, config, donk
from aurora.main import build_parser, run
from aurora.utils.process import run_process

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

FAILED_EXIT_CODE = 3
EXPECTED_LINT_COMMANDS = 3
INTERRUPTED_EXIT_CODE = 130
CONFIG_ERROR_EXIT_CODE = 2


def test_bare_cli_and_about_are_non_effectful(capsys: pytest.CaptureFixture[str]) -> None:
    assert run([]) == 0
    assert run(["about"]) == 0
    output = capsys.readouterr().out
    assert "AuroraBot 运行时" in output
    assert "四角色消息" in output


def test_each_command_registers_its_own_executor() -> None:
    parser = build_parser()

    about_arguments = parser.parse_args([about.NAME])
    check_arguments = parser.parse_args([check.NAME])
    config_arguments = parser.parse_args([config.NAME, "list"])
    donk_arguments = parser.parse_args([donk.NAME, "show"])

    assert about_arguments.executor is about.execute
    assert check_arguments.executor is check.execute
    assert config_arguments.executor is config.execute
    assert donk_arguments.executor is donk.execute


def test_config_command_lists_and_shows_registered_sources(
    configured_project: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert run(["--root", str(configured_project), config.NAME, "list"]) == 0
    listing = capsys.readouterr().out
    assert "runtime\tconfig/runtime.toml" in listing
    assert "profiles.dev\tconfig/profiles/dev.toml" in listing

    assert run(["--root", str(configured_project), config.NAME, "show", "runtime"]) == 0
    shown = capsys.readouterr().out
    assert "[runtime.tree]" in shown
    assert 'profile = "builtin.root"' in shown


def test_config_command_rejects_unknown_name(
    configured_project: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert run(["--root", str(configured_project), config.NAME, "show", "unknown"]) == CONFIG_ERROR_EXIT_CODE
    assert "未知配置：unknown" in capsys.readouterr().err


def test_config_command_reports_load_error(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail_load(_root: Path) -> None:
        raise ValueError("字段无效")

    monkeypatch.setattr(config, "load_config", fail_load)

    assert run([config.NAME, "list"]) == CONFIG_ERROR_EXIT_CODE
    assert "配置加载失败：字段无效" in capsys.readouterr().err


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
    arguments = build_parser().parse_args([check.NAME, "--lint"])

    assert check.execute(arguments) == 1
    assert len(calls) == EXPECTED_LINT_COMMANDS
    assert "1 项检查失败" in capsys.readouterr().err


def test_check_fix_flags_and_test_selection(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, ...]] = []

    def fake_run(command: tuple[str, ...], _root: Path) -> int:
        calls.append(command)
        return 0

    monkeypatch.setattr(check, "run_process", fake_run)
    parser = build_parser()

    assert check.execute(parser.parse_args([check.NAME, "--lint", "--fix", "--unsafe-fixes"])) == 0
    assert "--fix" in calls[0]
    assert "--unsafe-fixes" in calls[0]
    assert "--check" not in calls[1]

    calls.clear()
    assert check.execute(parser.parse_args([check.NAME, "--test"])) == 0
    assert len(calls) == 1
    assert "pytest" in calls[0]


def test_donk_show_runs_tool_and_reports_chinese_version(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "1.2.3"\n', encoding="utf-8")
    calls: list[tuple[str, ...]] = []

    def fake_run(command: tuple[str, ...], _root: Path) -> int:
        calls.append(command)
        return 0

    monkeypatch.setattr(donk, "run_process", fake_run)
    arguments = build_parser().parse_args(["--root", str(tmp_path), donk.NAME, "show"])

    assert donk.execute(arguments) == 0
    assert calls[0][3:5] == ("donk", "show")
    assert "当前版本：1.2.3" in capsys.readouterr().out


def test_donk_preserves_failure_code(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(donk, "run_process", lambda _command, _root: FAILED_EXIT_CODE)
    arguments = build_parser().parse_args(["--root", str(tmp_path), donk.NAME, "patch"])

    assert donk.execute(arguments) == FAILED_EXIT_CODE


def test_process_boundary_reports_failure_and_interrupt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class Result:
        returncode = FAILED_EXIT_CODE

    monkeypatch.setattr("aurora.utils.process.subprocess.run", lambda *_args, **_kwargs: Result())
    assert run_process(("example",), tmp_path) == FAILED_EXIT_CODE
    assert "命令失败" in capsys.readouterr().err

    def interrupt(*_args: object, **_kwargs: object) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr("aurora.utils.process.subprocess.run", interrupt)
    assert run_process(("example",), tmp_path) == INTERRUPTED_EXIT_CODE

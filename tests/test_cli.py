from __future__ import annotations

import os
import re
from typing import TYPE_CHECKING, Any, cast

import pytest

from aurora.commander import build_parser as _build_parser
from aurora.commander import build_registry
from aurora.commander import run as _run
from aurora.commands import DEFAULT_REGISTRY, CommandSpec, about, check, config, docs, donk, panel, setup, start
from aurora.utils import pnpm
from aurora.utils.environment import load_project_env
from aurora.utils.exit_code import EXIT_CONFIG_ERROR, EXIT_FAILURE, EXIT_INTERRUPTED
from aurora.utils.process import run_process

if TYPE_CHECKING:
    import argparse
    from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    """以默认命令目录构建顶层解析器。"""
    return _build_parser(DEFAULT_REGISTRY)


def run(arguments: list[str] | None = None) -> int:
    """按默认命令目录运行 CLI 输入，与 aurora.main.main 的分派一致。"""
    return _run(arguments, registry=DEFAULT_REGISTRY)


FAILED_EXIT_CODE = 3
EXPECTED_LINT_COMMANDS = 3
SETUP_PYTHON_STEPS = 2


def test_bare_cli_and_about_show_ascii_art_without_effects(capsys: pytest.CaptureFixture[str]) -> None:
    assert run([]) == 0
    assert run(["about"]) == 0
    output = capsys.readouterr().out
    assert "AuroraBot 运行时" in output
    assert "▄▀▀█ █  █ █▀▀▀ █▀▀█ █▀▀▀ ▄▀▀█ █▀▀█ █▀▀█ ▀█▀▀" in output
    assert "▀▀▀▀ ▀▀▀▀ ▀    ▀▀▀▀ ▀    ▀▀▀▀ ▀▀▀▀ ▀▀▀▀  ▀▀▀" in output


def test_about_reports_os_version_and_revision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "1.2.3"\n', encoding="utf-8")
    monkeypatch.setattr(about, "detect_os", lambda: "测试系统")
    monkeypatch.setattr(about, "get_project_version", lambda _root: "1.2.3")
    monkeypatch.setattr(about, "get_git_revision", lambda _root: "abc1234")

    assert run(["--root", str(tmp_path), about.COMMAND["name"]]) == 0
    output = capsys.readouterr().out
    assert "系统：测试系统" in output
    assert "版本：1.2.3" in output
    assert "提交：abc1234" in output
    assert "AuroraBot" in output


def test_missing_subcommand_prints_command_help(capsys: pytest.CaptureFixture[str]) -> None:
    assert run([config.COMMAND["name"]]) == 0
    output = capsys.readouterr().out
    assert "列出全部已注册配置" in output
    assert "显示一份配置的原始 TOML" in output

    assert run([donk.COMMAND["name"]]) == 0
    output = capsys.readouterr().out
    assert "升级主版本号" in output
    assert "升级修订版本号" in output


def test_each_command_registers_its_own_executor() -> None:
    parser = build_parser()

    about_arguments = parser.parse_args([about.COMMAND["name"]])
    check_arguments = parser.parse_args([check.COMMAND["name"]])
    config_arguments = parser.parse_args([config.COMMAND["name"], "list"])
    donk_arguments = parser.parse_args([donk.COMMAND["name"], "show"])
    setup_arguments = parser.parse_args([setup.COMMAND["name"]])
    start_arguments = parser.parse_args([start.COMMAND["name"], "--headless"])
    docs_arguments = parser.parse_args([docs.COMMAND["name"], "build", "--", "--base", "/foo"])
    panel_arguments = parser.parse_args([panel.COMMAND["name"], "dev"])

    assert about_arguments.executor is about.execute
    assert check_arguments.executor is check.execute
    assert config_arguments.executor is config.execute
    assert donk_arguments.executor is donk.execute
    assert setup_arguments.executor is setup.execute
    assert start_arguments.executor is start.execute
    assert docs_arguments.executor is docs.execute
    assert panel_arguments.executor is panel.execute
    assert "显示帮助并退出" in parser.format_help()


def test_start_loads_configuration_and_runs_shared_lifecycle(
    configured_project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order: list[str] = []
    calls: list[tuple[object, bool]] = []

    def fake_load_env(root: Path) -> bool:
        assert root == configured_project
        order.append("env")
        return True

    original_load_config = start._load_configuration

    def tracked_load_config(root: Path) -> object:
        order.append("config")
        return original_load_config(root)

    async def fake_run(configuration: object, *, headless: bool) -> None:
        order.append("runtime")
        calls.append((configuration, headless))

    monkeypatch.setattr(start, "load_project_env", fake_load_env)
    monkeypatch.setattr(start, "_load_configuration", tracked_load_config)
    monkeypatch.setattr(start, "_run_project", fake_run)

    assert run(["--root", str(configured_project), start.COMMAND["name"], "--headless"]) == 0
    assert order == ["env", "config", "runtime"]
    assert len(calls) == 1
    assert calls[0][1] is True


def test_project_env_only_fills_missing_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / ".env").write_text(
        "AURORA_FROM_DOTENV=文件值\nAURORA_PROCESS_VALUE=文件值\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("AURORA_FROM_DOTENV", raising=False)
    monkeypatch.setenv("AURORA_PROCESS_VALUE", "进程值")

    assert load_project_env(tmp_path) is True
    assert os.environ["AURORA_FROM_DOTENV"] == "文件值"
    assert os.environ["AURORA_PROCESS_VALUE"] == "进程值"


def test_missing_project_env_is_empty_input(tmp_path: Path) -> None:
    assert load_project_env(tmp_path) is False


def test_start_reports_configuration_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail_load(_root: Path) -> None:
        raise ValueError("模型配置错误")

    monkeypatch.setattr(start, "_load_configuration", fail_load)

    assert run([start.COMMAND["name"], "--headless"]) == EXIT_CONFIG_ERROR
    assert "启动失败：模型配置错误" in capsys.readouterr().err


def test_config_command_lists_and_shows_registered_sources(
    configured_project: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert run(["--root", str(configured_project), config.COMMAND["name"], "list"]) == 0
    listing = capsys.readouterr().out
    assert re.search(r"^runtime\s+\|\s+config/runtime\.toml$", listing, re.MULTILINE)
    assert re.search(r"^profiles\s+\|\s+config/profiles\.toml$", listing, re.MULTILINE)

    assert run(["--root", str(configured_project), config.COMMAND["name"], "show", "runtime"]) == 0
    shown = capsys.readouterr().out
    assert "[runtime.tree]" in shown
    assert 'agent = "builtin.root"' in shown


def test_config_command_rejects_unknown_name(
    configured_project: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert run(["--root", str(configured_project), config.COMMAND["name"], "show", "unknown"]) == EXIT_CONFIG_ERROR
    assert "未知配置：unknown" in capsys.readouterr().err


def test_config_command_reports_load_error(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail_load(_root: Path) -> None:
        raise ValueError("字段无效")

    monkeypatch.setattr(config, "load_config", fail_load)

    assert run([config.COMMAND["name"], "list"]) == EXIT_CONFIG_ERROR
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
    arguments = build_parser().parse_args(["--root", str(tmp_path), donk.COMMAND["name"], "show"])

    assert donk.execute(arguments) == 0
    assert calls[0][3:5] == ("donk", "show")
    assert "当前版本：1.2.3" in capsys.readouterr().out


def test_donk_preserves_failure_code(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(donk, "run_process", lambda _command, _root: FAILED_EXIT_CODE)
    arguments = build_parser().parse_args(["--root", str(tmp_path), donk.COMMAND["name"], "patch"])

    assert donk.execute(arguments) == FAILED_EXIT_CODE


def test_setup_bootstraps_dependencies_submodules_and_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "config.example").mkdir()
    (tmp_path / "config.example" / "runtime.toml").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / ".env.example").write_text("DEEPSEEK_API_KEY=\n", encoding="utf-8")
    calls: list[tuple[tuple[str, ...], Path]] = []

    def fake_run(command: tuple[str, ...], root: Path) -> int:
        calls.append((command, root))
        return 0

    monkeypatch.setattr(setup, "run_process", fake_run)
    monkeypatch.setattr(setup.shutil, "which", lambda _name: "/usr/bin/pnpm")
    arguments = build_parser().parse_args(["--root", str(tmp_path), setup.COMMAND["name"]])

    assert setup.execute(arguments) == 0
    assert (tmp_path / "config" / "runtime.toml").read_text(encoding="utf-8") == "x = 1\n"
    assert (tmp_path / ".env").read_text(encoding="utf-8") == "DEEPSEEK_API_KEY=\n"
    assert calls == [
        (("uv", "sync"), tmp_path),
        (("git", "submodule", "update", "--init", "docs", "panel"), tmp_path),
        (("pnpm", "install", "--frozen-lockfile"), tmp_path / "docs"),
        (("pnpm", "install", "--frozen-lockfile"), tmp_path / "panel"),
    ]


def test_setup_keeps_existing_personal_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (tmp_path / "config.example").mkdir()
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "runtime.toml").write_text("personal\n", encoding="utf-8")
    (tmp_path / ".env.example").write_text("DEEPSEEK_API_KEY=\n", encoding="utf-8")
    monkeypatch.setattr(setup, "run_process", lambda _command, _root: 0)
    arguments = build_parser().parse_args(["--root", str(tmp_path), setup.COMMAND["name"]])

    assert setup.execute(arguments) == 0
    assert (tmp_path / "config" / "runtime.toml").read_text(encoding="utf-8") == "personal\n"
    assert "config/ 已存在" in capsys.readouterr().out


def test_setup_keeps_existing_env_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (tmp_path / "config.example").mkdir()
    (tmp_path / ".env").write_text("KEEP=1\n", encoding="utf-8")
    monkeypatch.setattr(setup, "run_process", lambda _command, _root: 0)
    arguments = build_parser().parse_args(["--root", str(tmp_path), setup.COMMAND["name"]])

    assert setup.execute(arguments) == 0
    assert (tmp_path / ".env").read_text(encoding="utf-8") == "KEEP=1\n"
    assert ".env 已存在" in capsys.readouterr().out


def test_setup_reports_missing_config_template(tmp_path: Path) -> None:
    arguments = build_parser().parse_args(["--root", str(tmp_path), setup.COMMAND["name"]])

    assert setup.execute(arguments) == EXIT_FAILURE


def test_setup_stops_on_first_failed_step(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (tmp_path / "config.example").mkdir()
    (tmp_path / ".env.example").write_text("DEEPSEEK_API_KEY=\n", encoding="utf-8")
    monkeypatch.setattr(setup, "run_process", lambda _command, _root: FAILED_EXIT_CODE)
    arguments = build_parser().parse_args(["--root", str(tmp_path), setup.COMMAND["name"]])

    assert setup.execute(arguments) == EXIT_FAILURE
    assert "同步 Python 依赖失败。" in capsys.readouterr().err


def test_setup_skips_node_dependencies_without_pnpm(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (tmp_path / "config.example").mkdir()
    (tmp_path / ".env.example").write_text("DEEPSEEK_API_KEY=\n", encoding="utf-8")
    calls: list[tuple[tuple[str, ...], Path]] = []

    def fake_run(command: tuple[str, ...], root: Path) -> int:
        calls.append((command, root))
        return 0

    monkeypatch.setattr(setup, "run_process", fake_run)
    monkeypatch.setattr(setup.shutil, "which", lambda _name: None)
    arguments = build_parser().parse_args(["--root", str(tmp_path), setup.COMMAND["name"]])

    assert setup.execute(arguments) == 0
    assert len(calls) == SETUP_PYTHON_STEPS
    assert "未找到 pnpm" in capsys.readouterr().err


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


def test_docs_command_passes_script_and_passthrough_to_pnpm(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "package.json").write_text("{}\n", encoding="utf-8")
    calls: list[tuple[tuple[str, ...], Path]] = []

    def fake_run(command: tuple[str, ...], root: Path) -> int:
        calls.append((command, root))
        return 0

    monkeypatch.setattr(pnpm, "run_process", fake_run)
    monkeypatch.setattr(pnpm.shutil, "which", lambda _name: "/usr/bin/pnpm")
    arguments = build_parser().parse_args(
        ["--root", str(tmp_path), docs.COMMAND["name"], "build", "--", "--base", "/foo"]
    )

    assert docs.execute(arguments) == 0
    assert calls == [(("pnpm", "build", "--base", "/foo"), tmp_path / "docs")]


def test_panel_command_passes_passthrough_without_separator(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (tmp_path / "panel").mkdir()
    (tmp_path / "panel" / "package.json").write_text("{}\n", encoding="utf-8")
    calls: list[tuple[tuple[str, ...], Path]] = []

    def fake_run(command: tuple[str, ...], root: Path) -> int:
        calls.append((command, root))
        return 0

    monkeypatch.setattr(pnpm, "run_process", fake_run)
    monkeypatch.setattr(pnpm.shutil, "which", lambda _name: "/usr/bin/pnpm")
    arguments = build_parser().parse_args(["--root", str(tmp_path), panel.COMMAND["name"], "dev", "--port", "5173"])

    assert panel.execute(arguments) == 0
    assert calls == [(("pnpm", "dev", "--port", "5173"), tmp_path / "panel")]


def test_submodule_command_reports_uninitialized_submodule(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    arguments = build_parser().parse_args(["--root", str(tmp_path), docs.COMMAND["name"], "dev"])

    assert docs.execute(arguments) == EXIT_FAILURE
    assert "docs 子模块未初始化" in capsys.readouterr().err


def test_submodule_command_reports_missing_pnpm(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (tmp_path / "panel").mkdir()
    (tmp_path / "panel" / "package.json").write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(pnpm.shutil, "which", lambda _name: None)
    arguments = build_parser().parse_args(["--root", str(tmp_path), panel.COMMAND["name"], "dev"])

    assert panel.execute(arguments) == EXIT_FAILURE
    assert "未找到 pnpm" in capsys.readouterr().err


def test_submodule_command_preserves_failure_code(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "package.json").write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(pnpm, "run_process", lambda _command, _root: FAILED_EXIT_CODE)
    monkeypatch.setattr(pnpm.shutil, "which", lambda _name: "/usr/bin/pnpm")
    arguments = build_parser().parse_args(["--root", str(tmp_path), docs.COMMAND["name"], "dev"])

    assert docs.execute(arguments) == FAILED_EXIT_CODE


def test_commander_rejects_empty_passthrough_help() -> None:
    with pytest.raises(ValueError, match="透传参数帮助文本不能为空"):
        build_registry(((cast("CommandSpec", {**docs.COMMAND, "passthrough": "  "}), docs.execute),))

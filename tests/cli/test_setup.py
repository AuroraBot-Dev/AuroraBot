from __future__ import annotations

from typing import TYPE_CHECKING

from aurora_cli.commands import setup
from aurora_cli.utils.process import EXIT_FAILURE
from tests.cli.support import FAILED_EXIT_CODE, SETUP_PYTHON_STEPS, build_parser

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def test_setup_bootstraps_dependencies_and_config(
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
        (("pnpm", "install", "--frozen-lockfile"), tmp_path),
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


def test_setup_skips_node_dependencies_without_process(
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


def test_setup_config_flag_only_copies_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "config.example").mkdir()
    (tmp_path / "config.example" / "runtime.toml").write_text("x = 1\n", encoding="utf-8")
    calls: list[tuple[tuple[str, ...], Path]] = []

    def fake_run(command: tuple[str, ...], root: Path) -> int:
        calls.append((command, root))
        return 0

    monkeypatch.setattr(setup, "run_process", fake_run)
    arguments = build_parser().parse_args(["--root", str(tmp_path), setup.COMMAND["name"], "--config"])

    assert setup.execute(arguments) == 0
    assert (tmp_path / "config" / "runtime.toml").read_text(encoding="utf-8") == "x = 1\n"
    assert not (tmp_path / ".env").exists()
    assert calls == []


def test_setup_combines_selected_flags_in_order(
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
    arguments = build_parser().parse_args(
        ["--root", str(tmp_path), setup.COMMAND["name"], "--python", "--env", "--panel"]
    )

    assert setup.execute(arguments) == 0
    assert (tmp_path / ".env").read_text(encoding="utf-8") == "DEEPSEEK_API_KEY=\n"
    assert not (tmp_path / "config").exists()
    assert calls == [
        (("uv", "sync"), tmp_path),
        (("pnpm", "install", "--frozen-lockfile"), tmp_path),
    ]

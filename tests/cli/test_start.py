from __future__ import annotations

import os
import runpy
from typing import TYPE_CHECKING

from aurora.commands import start
from aurora.utils.environment import load_project_env
from aurora.utils.process import EXIT_CONFIG_ERROR, EXIT_INTERRUPTED
from tests import PROJECT_ROOT
from tests.cli.support import run

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def test_start_loads_config_and_runs_shared_lifecycle(
    configured_project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order: list[str] = []
    calls: list[tuple[object, bool]] = []

    def fake_load_env(root: Path) -> bool:
        assert root == configured_project
        order.append("env")
        return True

    original_load_config = start._load_config

    def tracked_load_config(root: Path) -> object:
        order.append("config")
        return original_load_config(root)

    async def fake_run(config: object, *, headless: bool) -> None:
        order.append("runtime")
        calls.append((config, headless))

    monkeypatch.setattr(start, "load_project_env", fake_load_env)
    monkeypatch.setattr(start, "_load_config", tracked_load_config)
    monkeypatch.setattr(start, "_run_runtime", fake_run)

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


def test_start_reports_config_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail_load(_root: Path) -> None:
        raise ValueError("模型配置错误")

    monkeypatch.setattr(start, "_load_config", fail_load)

    assert run([start.COMMAND["name"], "--headless"]) == EXIT_CONFIG_ERROR
    assert "启动失败：模型配置错误" in capsys.readouterr().err


def test_start_runs_real_shared_lifecycle(
    configured_project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[object, bool]] = []

    async def fake_run_project(config: object, *, headless: bool, stop_event: object) -> None:
        calls.append((config, headless))

    monkeypatch.setattr("aurorabot.runtime.run_runtime", fake_run_project)

    assert run(["--root", str(configured_project), start.COMMAND["name"], "--headless"]) == 0
    assert len(calls) == 1
    assert calls[0][1] is True


def test_start_maps_keyboard_interrupt_to_exit_code(monkeypatch: pytest.MonkeyPatch) -> None:
    async def interrupted(config: object, *, headless: bool) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(start, "_load_config", lambda _root: object())
    monkeypatch.setattr(start, "configure_project_logging", lambda _config: None)
    monkeypatch.setattr(start, "_run_runtime", interrupted)

    assert run([start.COMMAND["name"], "--headless"]) == EXIT_INTERRUPTED


def test_python_dash_m_aurora_dispatches_through_main(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[object] = []

    def fake_main(argv: object = None) -> None:
        calls.append(argv)

    monkeypatch.setattr("aurora.main.main", fake_main)
    runpy.run_path(str(PROJECT_ROOT / "src" / "aurora" / "__main__.py"), run_name="__main__")
    assert calls == [None]


def test_start_reports_each_runtime_and_cleanup_failure(
    configured_project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """异常组不能只显示错误数量，原始运行错误和清理错误均需可读。"""

    async def failed(config: object, *, headless: bool) -> None:
        """模拟已经完成清理的运行失败。"""
        raise ExceptionGroup("运行与资源清理同时失败", [ValueError("原始运行错误"), OSError("释放失败")])

    monkeypatch.setattr(start, "_run_runtime", failed)
    assert run(["--root", str(configured_project), start.COMMAND["name"], "--headless"]) == EXIT_CONFIG_ERROR
    error = capsys.readouterr().err
    assert "原始运行错误" in error
    assert "释放失败" in error

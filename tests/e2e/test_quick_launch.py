"""从其他目录验证两组快捷命令的真实调用链，不连接产品服务。"""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("name,marker,launcher", [("bot", b"--env-file", "aurora"), ("panel", b"--host", "pnpm")])
def test_quick_command_help_from_other_directory(tmp_path, name, marker, launcher):
    pnpm = shutil.which("pnpm")
    if pnpm is None:
        pytest.skip("快捷前端命令需要工作区 pnpm")
    command = (
        [sys.executable, "-m", "aurora_cli", "--root", str(ROOT), name]
        if launcher == "aurora"
        else [pnpm, "--dir", str(ROOT), name]
    )
    result = subprocess.run([*command, "--help"], cwd=tmp_path, capture_output=True, timeout=30, check=False)
    assert result.returncode == 0, result.stderr
    assert marker in result.stdout
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("launcher", ["aurora", "pnpm"])
def test_tui_preferences_arguments_survive_both_launchers(tmp_path, launcher):
    pnpm = shutil.which("pnpm")
    if pnpm is None:
        pytest.skip("快捷前端命令需要工作区 pnpm")
    preferences = tmp_path / "独立偏好 with spaces.json"
    command = (
        [sys.executable, "-m", "aurora_cli", "--root", str(ROOT), "tui"]
        if launcher == "aurora"
        else [pnpm, "--dir", str(ROOT), "tui"]
    )
    result = subprocess.run(
        [
            *command,
            "--connect",
            "http://127.0.0.1:10279",
            "--instance",
            "独立实例 with spaces",
            "--token-env",
            "AURORA_TEST_TOKEN",
            "--preferences",
            str(preferences),
            "--save-preferences",
        ],
        cwd=tmp_path,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(preferences.read_text(encoding="utf-8")) == {
        "version": 1,
        "connect": "http://127.0.0.1:10279",
        "instance": "独立实例 with spaces",
        "page": "chat",
        "showTools": False,
    }

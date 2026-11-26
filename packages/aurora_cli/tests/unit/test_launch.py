"""快捷命令复用工作区脚本，保留参数、退出码和宿主收尾时间。"""

import asyncio
import subprocess
from io import StringIO
from unittest.mock import MagicMock

import pytest
from aurora_cli.commander import run_cli
from aurora_cli.commands import launch
from aurora_cli.utils import process


@pytest.mark.parametrize("name", ["bot", "panel", "tui"])
@pytest.mark.parametrize("arguments", [[], ["--help"], ["--instance", "有空格的实例", "--", "--literal"]])
def test_launch_dispatches_without_host_and_preserves_arguments(tmp_path, monkeypatch, name, arguments):
    root = tmp_path / "workspace with spaces"
    (root / "scripts").mkdir(parents=True)
    script = root / "scripts" / f"{name}.py"
    script.touch()
    (root / "pyproject.toml").touch()
    monkeypatch.chdir(tmp_path)
    calls = []

    def execute(command, *, root, output):
        calls.append((command, root))
        return 7

    monkeypatch.setattr(launch, "run_process", execute)
    assert asyncio.run(run_cli(["--root", str(root), name, *arguments], output=StringIO())) == 7
    assert calls == [(["uv", "run", "--locked", "python", str(script), *arguments], root)]
    assert not (root / "data").exists()


@pytest.mark.parametrize("name", ["bot", "panel", "tui"])
def test_launch_requires_workspace_scripts(tmp_path, monkeypatch, name):
    def unexpected(*args, **kwargs):
        pytest.fail("缺失脚本时不应创建子进程")

    monkeypatch.setattr(launch, "run_process", unexpected)
    with pytest.raises(ValueError, match="请指定 --root"):
        asyncio.run(run_cli(["--root", str(tmp_path), name], output=StringIO()))


@pytest.mark.parametrize("interrupt_again", [False, True])
def test_interrupt_waits_for_cleanup_before_termination(tmp_path, monkeypatch, interrupt_again):
    child = MagicMock()
    child.__enter__.return_value = child
    timeout = subprocess.TimeoutExpired("tool", 5)
    child.wait.side_effect = (
        [KeyboardInterrupt(), KeyboardInterrupt(), timeout, 0] if interrupt_again else [KeyboardInterrupt(), 0]
    )
    monkeypatch.setattr(process.shutil, "which", lambda name: name)
    monkeypatch.setattr(process.subprocess, "Popen", lambda *args, **kwargs: child)
    with pytest.raises(KeyboardInterrupt):
        process.run_process(["tool"], root=tmp_path, output=StringIO())
    assert child.wait.call_args_list[1].kwargs == {}
    assert child.terminate.called is interrupt_again
    assert child.kill.called is interrupt_again

"""以真实示例进程验证四类控制组件的可见输出和最近一次运行结果。"""

import json
import os
import subprocess
import sys
from pathlib import Path


def test_control_flow_example_interrupt_persists_cancelled_state(tmp_path):
    application = (
        Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "runtime_apps" / "control_flow" / "main.py"
    )
    # 两个计算均启动后发送真实 SIGINT，运行入口仍使用示例自身的 main。
    launcher = """
import asyncio
import runpy
import signal
import sys

source = runpy.run_path(sys.argv[1])
original = source["observe"]

def observe(change):
    original(change)
    if dict(change.address.location)["instance_id"] == "square" and change.value == {"status": "running"}:
        asyncio.get_running_loop().call_soon(signal.raise_signal, signal.SIGINT)

source["main"].__globals__["observe"] = observe
sys.argv = [sys.argv[1], "--data-dir", sys.argv[2], "--steps", "1", "--delay", "0.1"]
source["main"]()
"""
    result = subprocess.run(
        [sys.executable, "-c", launcher, str(application), str(tmp_path)],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        timeout=15,
    )
    assert result.returncode == 130, result.stderr
    assert "[控制] root: cancelled" in result.stdout
    assert "已取消。" in result.stdout
    snapshot = json.loads((tmp_path / "framework" / "ctx.json").read_text(encoding="utf-8"))
    assert len(snapshot["entries"]) == 1
    assert snapshot["entries"][0]["value"] == {"status": "cancelled"}

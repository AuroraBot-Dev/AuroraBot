"""独立进程验证工具桥分层与默认 bot 的发现顺序，不访问外部模型或 MCP 服务。"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    "with_bot,protocol,transport,automatic",
    [(False, "legacy", "remote", False), (True, "auto", "local", True)],
)
def test_local_mcp_tools_roundtrip(tmp_path, with_bot, protocol, transport, automatic):
    launcher = """
import importlib.abc
import runpy
import sys
blocked = {'aurora_cli', 'aurora_api'}
if '--bot' not in sys.argv:
    blocked.update({'aurora_world', 'aurora_bot'})
class AbsentPackages(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in blocked:
            raise ModuleNotFoundError('工具宿主不提供：' + fullname)
sys.meta_path.insert(0, AbsentPackages())
source = sys.argv.pop(1)
runpy.run_path(source, run_name='__main__')
assert not blocked.intersection(name.split('.')[0] for name in sys.modules)
"""
    fixture = Path(__file__).resolve().parents[1] / "fixtures" / "mcp_tools_roundtrip.py"
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            launcher,
            str(fixture),
            str(tmp_path),
            "--protocol",
            protocol,
            "--transport",
            transport,
            *(["--bot"] if with_bot else []),
            *(["--automatic"] if automatic else []),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"tool_bridge": True, "default_bot": with_bot, "calls": 1 if with_bot else 2}

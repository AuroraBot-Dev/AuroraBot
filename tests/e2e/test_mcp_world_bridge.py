"""通过独立进程验证 MCP 通知写入 world、恢复去重及来源隔离。"""

import json
import os
import subprocess
import sys
from pathlib import Path


def test_mcp_world_roundtrip_without_agent_or_product_packages(tmp_path):
    launcher = """
import importlib.abc
import runpy
import sys
blocked = {'aurora_agent', 'aurora_bot', 'aurora_control', 'aurora_adapter.model', 'aurora_cli', 'aurora_api'}
class AbsentPackages(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if any(fullname == item or fullname.startswith(item + '.') for item in blocked):
            raise ModuleNotFoundError('MCP 世界来源环境不提供：' + fullname)
sys.meta_path.insert(0, AbsentPackages())
source = sys.argv.pop(1)
runpy.run_path(source, run_name='__main__')
assert not any(name == item or name.startswith(item + '.') for name in sys.modules for item in blocked)
"""
    fixture = Path(__file__).resolve().parents[1] / "fixtures" / "mcp_world_roundtrip.py"
    identities = []
    for counts in ([2, 3], [4, 5]):
        result = subprocess.run(
            [sys.executable, "-c", launcher, str(fixture), str(tmp_path)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            check=False,
        )
        assert result.returncode == 0, result.stderr
        report = json.loads(result.stdout)
        identities.append(report.pop("record_id"))
        assert report == {
            "counts": counts,
            "stable_record": True,
            "shared_client": True,
            "disconnect_reported": True,
            "subscriptions": 4,
        }
    assert identities[0] == identities[1]

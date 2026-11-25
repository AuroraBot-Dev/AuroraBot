"""验证执行包的独立加载、插件发现与命名空间归属。"""

import json
import os
import subprocess
import sys
from pathlib import Path


def test_control_runs_without_agent_bot_or_model_packages(tmp_path):
    launcher = """
import importlib.abc
import runpy
import sys

blocked = {'aurora_agent', 'aurora_bot', 'aurora_adapter', 'aurora_cli', 'aurora_api'}

class AbsentPackages(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in blocked:
            raise ModuleNotFoundError('独立控制环境不提供：' + fullname)

sys.meta_path.insert(0, AbsentPackages())
from aurora_core.discovery import load_plugins
plugins = load_plugins(enabled=['aurora_control'])
assert plugins[0].entries[0].provider == 'aurora_control'
source = sys.argv.pop(1)
runpy.run_path(source, run_name='__main__')
assert not blocked.intersection(name.split('.')[0] for name in sys.modules)
"""
    example = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "runtime_apps" / "control_flow" / "main.py"
    result = subprocess.run(
        [sys.executable, "-c", launcher, str(example), "--data-dir", str(tmp_path), "--delay", "0"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        timeout=15,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert '"status": "completed"' in (tmp_path / "framework" / "ctx.json").read_text(encoding="utf-8")


def test_agent_roundtrip_and_restore_without_bot_or_hosts(tmp_path):
    launcher = """
import importlib.abc
import runpy
import sys

blocked = {'aurora_bot', 'aurora_cli', 'aurora_api'}

class AbsentPackages(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in blocked:
            raise ModuleNotFoundError('独立 agent 环境不提供：' + fullname)

sys.meta_path.insert(0, AbsentPackages())
from aurora_agent.runtime import AgentRuntime
from aurora_core.discovery import load_plugins
plugins = load_plugins(enabled=[
    'aurora_agent.model', 'aurora_agent.react', 'aurora_agent.tools', 'aurora_agent.react_defaults',
])
assert all(entry.provider == 'aurora_agent' for plugin in plugins for entry in plugin.entries)
source = sys.argv.pop(1)
runpy.run_path(source, run_name='__main__')
assert not blocked.intersection(name.split('.')[0] for name in sys.modules)
"""
    example = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "runtime_apps" / "react_agent" / "main.py"
    states = []
    for options in (["--guide", "保持计算进度"], ["--text", "无需行动"]):
        result = subprocess.run(
            [sys.executable, "-c", launcher, str(example), "--data-dir", str(tmp_path), *options],
            capture_output=True,
            text=True,
            encoding="utf-8",
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            timeout=15,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        entries = json.loads((tmp_path / "framework" / "ctx.json").read_text(encoding="utf-8"))["entries"]
        states.append({entry["location"]["name"]: entry["value"] for entry in entries})
    first, restored = states
    assert first["runtime"]["status"] == restored["runtime"]["status"] == "completed"
    assert first["progress"] == 2 and restored["progress"] == 3
    assert restored["context"]["messages"][:-1] == first["context"]["messages"]
    assert any(message["role"] == "tool" for message in first["context"]["messages"])


def test_model_protocol_and_plugin_discovery_do_not_import_sdks():
    launcher = """
import importlib.abc
import sys
blocked = {'litellm', 'mcp', 'httpx', 'httpx2', 'aurora_agent', 'aurora_bot', 'aurora_world'}
class AbsentPackages(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in blocked:
            raise ModuleNotFoundError('模型发现环境不提供：' + fullname)
sys.meta_path.insert(0, AbsentPackages())
from aurora_adapter.model.testing import FakeModel, FakeReply
from aurora_adapter.model.config import ADAPTERS, ModelAdapter
from aurora_core.discovery import load_plugins
plugins = load_plugins(enabled=['aurora_config', 'aurora_adapter.model'])
plugin = next(item for item in plugins if item.name == 'aurora_adapter.model')
assert {
    'org.aurora.adapter:registries/model/adapters',
    'org.aurora.adapter:services/model/chat_client',
    'org.aurora.adapter:services/model/choice_client',
    'org.aurora.adapter:adapters/model/litellm/choice',
    'org.aurora.adapter:services/model/embedding_client',
    'org.aurora.adapter:adapters/model/litellm/chat',
    'org.aurora.adapter:adapters/model/litellm/embedding',
} <= {str(entry.id) for entry in plugin.entries}
adapters = [entry for entry in plugin.entries if entry.kind == 'adapter']
assert all(isinstance(entry.target, ModelAdapter) and entry.register_to == ADAPTERS for entry in adapters)
assert {entry.target.kind for entry in adapters} == {'chat', 'choice', 'embedding'}
assert all(entry.id.namespace == 'org.aurora.adapter' for entry in plugin.entries)
assert not blocked.intersection(name.split('.')[0] for name in sys.modules)
"""
    result = subprocess.run([sys.executable, "-c", launcher], capture_output=True, text=True, timeout=15, check=False)
    assert result.returncode == 0, result.stderr


def test_default_bot_runs_when_cli_and_api_imports_are_unavailable(tmp_path):
    launcher = """
import importlib.abc
import runpy
import sys

class AbsentHosts(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'aurora_cli', 'aurora_api'}:
            raise ModuleNotFoundError('验收环境未安装可选宿主：' + fullname)

sys.meta_path.insert(0, AbsentHosts())
source = sys.argv.pop(1)
from pathlib import Path
sys.path.insert(0, str(Path(source).parent))
runpy.run_path(source, run_name='__main__')
assert not any(name.split('.')[0] in {'aurora_cli', 'aurora_api'} for name in sys.modules)
"""
    example = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "runtime_apps" / "default_bot" / "main.py"
    result = subprocess.run(
        [sys.executable, "-c", launcher, str(example), "--data-dir", str(tmp_path), "--text", "隔离验收"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        timeout=15,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "内部输出: 模型一:回显:隔离验收" in result.stdout
    assert (tmp_path / "framework" / "ctx.json").is_file()

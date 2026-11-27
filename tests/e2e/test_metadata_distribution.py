"""从 sdist 隔离构建真实插件 wheel，并在禁止运行包导入时读取发行目录。"""

import os
import subprocess
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_metadata_build_tool_and_sdists_are_independent_of_workspace_runtime(tmp_path):
    environment = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}

    def build(source, *options):
        result = subprocess.run(
            ["uv", "build", str(source), "--python", sys.executable, "--out-dir", str(tmp_path), *options],
            cwd=tmp_path,
            env=environment,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        assert result.returncode == 0, result.stderr

    build(ROOT / "tooling/aurora_meta_build", "--wheel", "--no-build-isolation")
    wheels = []
    for name in (
        "aurora_config",
        "aurora_control",
        "aurora_agent",
        "aurora_model",
        "aurora_mcp",
        "aurora_tools",
        "aurora_bot",
        "aurora_api",
    ):
        build(ROOT / "packages" / name, "--sdist", "--no-build-isolation")
        (sdist,) = tmp_path.glob(f"{name}-*.tar.gz")
        with tarfile.open(sdist) as archive:
            paths = archive.getnames()
            assert any(path.endswith("plugin.meta.toml") for path in paths)
            assert not any(path.endswith("/build_meta.py") for path in paths)
            if name == "aurora_config":
                assert any(path.endswith("/editor_contract.py") for path in paths)
            if name == "aurora_agent":
                assert any(path.endswith("/parameters.py") for path in paths)
        build(sdist, "--wheel", "--offline", "--no-sources", "--find-links", str(tmp_path))
        wheels.append(str(next(tmp_path.glob(f"{name}-*.whl"))))
    script = """
import importlib.abc
import sys
from pathlib import Path

class NoRuntime(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith(('aurora_core', 'aurora_config', 'aurora_control', 'aurora_agent', 'aurora_model', 'aurora_mcp', 'aurora_tools', 'aurora_bot', 'aurora_api', 'litellm', 'mcp')):
            raise AssertionError('静态操作不得导入运行包：' + fullname)

sys.meta_path.insert(0, NoRuntime())
from aurora_meta_build import generate, read_catalog
root = Path(sys.argv[1])
for wheel in sys.argv[2:]:
    sys.path.insert(0, wheel)
for name in ('aurora_config', 'aurora_control', 'aurora_agent', 'aurora_model', 'aurora_mcp', 'aurora_tools', 'aurora_bot', 'aurora_api'):
    generate(root / 'packages' / name, check=True)
    catalog = read_catalog(name.replace('_', '-'))
    assert catalog['schema_version'] == 2
    assert catalog['distribution']['name'] == name.replace('_', '-')
    assert catalog['manifests']
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(ROOT), *wheels],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 0, result.stderr

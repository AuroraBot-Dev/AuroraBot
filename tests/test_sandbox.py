# ruff: noqa: PLR2004
from __future__ import annotations

import asyncio
import os
from typing import TYPE_CHECKING

import pytest

import src.sandbox.executor as executor_module
import src.sandbox.policy as policy_module
from src.sandbox import SandboxManager
from src.sandbox.base import SandboxConfigError, SandboxResult, SecurityViolation
from src.sandbox.executor import SandboxExecutor
from src.sandbox.inspector import CodeInspector
from src.sandbox.policy import AccessPolicy
from src.sandbox.settings import ConfigReloader, SandboxConfig

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


def _configuration(root: Path) -> SandboxConfig:
    resolved = root.resolve()
    root_patterns = frozenset(
        {
            str(resolved / "*"),
            str(resolved / "*" / "*"),
            str(resolved / "*" / "*" / "*"),
        }
    )
    return SandboxConfig(
        whitelist_files=root_patterns,
        whitelist_dirs=root_patterns,
        whitelist_modules=frozenset({"json", "math", "pathlib"}),
        whitelist_builtins=frozenset({"len", "print", "range", "str", "sum"}),
        blacklist_files=frozenset({str(root.resolve() / "secret*")}),
        blacklist_dirs=frozenset({str(root.resolve() / "private*")}),
        blacklist_modules=frozenset({"os", "subprocess"}),
        blacklist_builtins=frozenset({"exec", "eval"}),
    )


@pytest.fixture
def sandbox_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    root = tmp_path / "sandbox"
    root.mkdir()
    monkeypatch.setattr(policy_module, "SANDBOX_DIR", root)
    monkeypatch.setattr(executor_module, "SANDBOX_DIR", root)
    monkeypatch.setattr(executor_module, "SANDBOX_TEMP_DIR", root / "temp")
    monkeypatch.setattr(executor_module, "SANDBOX_OUTPUT_DIR", root / "output")
    yield root


def test_sandbox_configuration_loads_and_reloads_valid_yaml(tmp_path: Path) -> None:
    root = tmp_path.resolve()
    config_path = tmp_path / "sandbox.yaml"

    def write(modules: str) -> None:
        config_path.write_text(
            f"""whitelist:
  files: ["{root.as_posix()}/**"]
  dirs: ["{root.as_posix()}/**"]
  modules: [{modules}]
  builtins: ["len", "print"]
blacklist:
  files: []
  dirs: []
  modules: ["os"]
  builtins: ["exec"]
""",
            encoding="utf-8",
        )

    write('"json"')
    loaded = SandboxConfig.from_yaml(config_path)
    assert loaded.whitelist_modules == frozenset({"json"})
    assert loaded.blacklist_builtins == frozenset({"exec"})

    received: list[SandboxConfig] = []
    reloader = ConfigReloader(config_path, received.append)
    reloader.check_and_reload()
    reloader.check_and_reload()
    assert len(received) == 1

    write('"json", "math"')
    current = config_path.stat().st_mtime_ns
    os.utime(config_path, ns=(current + 1_000_000_000, current + 1_000_000_000))
    reloader.check_and_reload()
    assert received[-1].whitelist_modules == frozenset({"json", "math"})

    config_path.write_text("not: valid: yaml: [", encoding="utf-8")
    reloader._last_mtime = 0
    reloader.check_and_reload()
    assert len(received) == 2


@pytest.mark.parametrize(
    ("content", "message"),
    (
        ("[]", "YAML"),
        ("whitelist: {}", "key"),
        ("whitelist: []\nblacklist: {}", "whitelist"),
        (
            "whitelist: {files: relative/**, dirs: [], modules: [], builtins: []}\n"
            "blacklist: {files: [], dirs: [], modules: [], builtins: []}",
            "list",
        ),
        (
            "whitelist: {files: [relative/**], dirs: [], modules: [], builtins: []}\n"
            "blacklist: {files: [], dirs: [], modules: [], builtins: []}",
            "absolute|绝对",
        ),
    ),
)
def test_sandbox_configuration_rejects_invalid_shapes(tmp_path: Path, content: str, message: str) -> None:
    path = tmp_path / "invalid.yaml"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(SandboxConfigError, match=message):
        SandboxConfig.from_yaml(path)

    with pytest.raises(SandboxConfigError):
        SandboxConfig.from_yaml(tmp_path / "missing.yaml")


def test_access_policy_enforces_precedence_paths_and_snapshot(sandbox_root: Path) -> None:
    policy = AccessPolicy(_configuration(sandbox_root))
    allowed = sandbox_root / "allowed.txt"
    secret = sandbox_root / "secret-token.txt"
    outside = sandbox_root.parent / "outside.txt"

    assert policy.can_import_module("json.decoder")
    assert not policy.can_import_module("os.path")
    assert not policy.can_import_module("unknown")
    assert policy.can_use_builtin("len")
    assert not policy.can_use_builtin("exec")
    assert policy.can_read_file(allowed)
    assert not policy.can_read_file(secret)
    assert policy.can_read_dir(sandbox_root / "public")
    assert not policy.can_read_dir(sandbox_root / "private-data")
    assert policy.can_open_file(allowed, "w")
    assert not policy.can_open_file(outside, "w")

    snapshot = policy.snapshot()
    policy.update_config(_configuration(sandbox_root.parent))
    assert "json" in snapshot.whitelist_modules
    assert policy.config.whitelist_files != snapshot.whitelist_files


@pytest.mark.parametrize(
    "code",
    (
        "x = 1\ndel x",
        "def f():\n    global x",
        'exec("print(1)")',
        "import os",
        "from subprocess import run",
        "x.__class__",
        "type(x).__mro__",
        'Path("x").unlink()',
        '"{0}".format(1)',
        "open(variable)",
    ),
)
def test_code_inspector_rejects_escape_and_access_patterns(sandbox_root: Path, code: str) -> None:
    inspector = CodeInspector(AccessPolicy(_configuration(sandbox_root)))
    assert inspector.inspect(code), code


def test_code_inspector_allows_declared_import_and_file(sandbox_root: Path) -> None:
    allowed = sandbox_root / "allowed.txt"
    allowed.write_text("ok", encoding="utf-8")
    inspector = CodeInspector(AccessPolicy(_configuration(sandbox_root)))

    assert inspector.inspect(f"import json\nopen({str(allowed)!r}, 'r')") == []
    assert inspector.inspect("def broken(") == []


def test_sandbox_executor_runs_code_and_handles_failures(sandbox_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    policy = AccessPolicy(_configuration(sandbox_root))
    executor = SandboxExecutor(policy, CodeInspector(policy))

    async def scenario() -> None:
        successful = await executor.execute('print(f"value={value}")', "success", {"value": 7})
        failed = await executor.execute("1 / 0", "failure")
        assert successful.success and successful.output.strip() == "value=7"
        assert not failed.success and "ZeroDivisionError" in (failed.error or "")

        monkeypatch.setattr(executor, "_check_disk_space", lambda: False)
        no_space = await executor.execute("print(1)", "no-space")
        assert not no_space.success

    asyncio.run(scenario())


def test_sandbox_executor_collects_artifacts_and_guards_file_access(sandbox_root: Path) -> None:
    policy = AccessPolicy(_configuration(sandbox_root))
    executor = SandboxExecutor(policy, CodeInspector(policy))
    execution_dir = sandbox_root / "execution"
    output_dir = sandbox_root / "output" / "artifacts"
    execution_dir.mkdir()
    output_dir.mkdir(parents=True)
    (execution_dir / "script.py").write_text("pass", encoding="utf-8")
    (execution_dir / "result.txt").write_text("result", encoding="utf-8")

    artifacts = executor._collect_artifacts(execution_dir, output_dir)
    assert artifacts == [output_dir / "result.txt"]
    assert executor.read_file(artifacts[0]) == "result"

    target = sandbox_root / "written.txt"
    executor.write_file(target, "written")
    assert target.read_text(encoding="utf-8") == "written"
    with pytest.raises(PermissionError):
        executor.write_file(sandbox_root.parent / "outside.txt", "blocked")


def test_sandbox_manager_validates_inspects_executes_and_calls_back(sandbox_root: Path) -> None:
    manager = SandboxManager()
    received: list[SandboxResult] = []

    async def scenario() -> None:
        successful = await manager.execute(
            'print(f"user={user}")', "valid-session", {"user": "Aurora"}, received.append
        )
        dangerous = await manager.execute("import os", "dangerous")
        syntax_error = await manager.execute("def broken(", "syntax")
        invalid_session = await manager.execute("print(1)", "../escape")

        assert successful.success and "user=Aurora" in successful.output
        assert dangerous.error is not None
        assert syntax_error.error is not None
        assert invalid_session.error is not None

    asyncio.run(scenario())
    assert received and received[0].success
    formatted = manager._format_violations([SecurityViolation("test", "detail", 3, "Call")])
    assert "line 3" in formatted and "[Call]" in formatted

    replacement = _configuration(sandbox_root)
    manager._on_config_updated(replacement)
    assert manager._policy.config is replacement


def test_sandbox_manager_singleton_proxy() -> None:
    import src.sandbox as sandbox_module

    sandbox_module._sandbox_singleton = None
    first = sandbox_module.get_sandbox_manager()
    second = sandbox_module.get_sandbox_manager()
    assert first is second
    assert sandbox_module.sandbox_manager._policy is first._policy

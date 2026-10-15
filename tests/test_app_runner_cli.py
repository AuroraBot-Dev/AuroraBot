"""``aurora app install --npx`` / ``--uvx``：包管理器型安装的 CLI 行为。

它与源码安装共用子命令与确认，但准入规则不同：没有仓库可读、没有清单
可查、没有 staging 可清理。这个文件锁住的就是「走了另一条路」这件事 —— 不 clone、
不读 ``aurora-app.toml``、连 verify 都连在项目根上。
"""

from __future__ import annotations

import io
import sys
from typing import TYPE_CHECKING

from app_clone_support import FakeCloner, apps_root_entries, registry_entry
from app_install_support import DEFAULT_PROTOCOL, FakeMcpClientFactory, FakeSource, stub_cli

from aurora.commander import run
from aurora.commands import DEFAULT_REGISTRY
from aurora.commands.app.verify import MCPVerifier
from aurora.utils.process import EXIT_CONFIG_ERROR, EXIT_FAILURE, EXIT_INTERRUPTED

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

_EMPTY_REGISTRY = "app = []\n"
_CONFIG = "config/apps.toml"
_SPECIFIER = "weather-mcp"
_NPX_PACKAGE = "npx.app.weather-mcp"
_UVX_PACKAGE = "uvx.app.weather-mcp"


def _project(tmp_path: Path, apps_toml: str = _EMPTY_REGISTRY) -> Path:
    config = tmp_path / "config"
    config.mkdir(parents=True, exist_ok=True)
    (config / "apps.toml").write_text(apps_toml, encoding="utf-8")
    return tmp_path


def _cli(root: Path, *arguments: str) -> int:
    return run(["--root", str(root), "app", *arguments], registry=DEFAULT_REGISTRY)


def _capture(capsys: pytest.CaptureFixture[str], root: Path, *arguments: str) -> tuple[int, str, str]:
    code = _cli(root, *arguments)
    streams = capsys.readouterr()
    return code, streams.out, streams.err


def _stub(
    monkeypatch: pytest.MonkeyPatch,
    *,
    manifest: str | None = None,
    factory: FakeMcpClientFactory | None = None,
) -> tuple[FakeSource, FakeCloner]:
    """包管理器路径的装配；默认连清单都是「没有」，用来证明这条路上没人读它。"""
    return stub_cli(monkeypatch, manifest=manifest, verifier=None if factory is None else MCPVerifier(factory))


def _factory() -> FakeMcpClientFactory:
    return FakeMcpClientFactory(protocol_version=DEFAULT_PROTOCOL)


class _Terminal(io.StringIO):
    """一个自称是终端的 stdin，里面放着用户将要敲的那一行。"""

    def isatty(self) -> bool:
        return True


def _pipe(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "stdin", io.StringIO())


def _terminal(monkeypatch: pytest.MonkeyPatch, answer: str = "n") -> None:
    monkeypatch.setattr(sys, "stdin", _Terminal(f"{answer}\n"))


# --- 正常路径 -------------------------------------------------------------------


def test_npx_registers_a_runnable_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _stub(monkeypatch)
    root = _project(tmp_path)

    code, out, _ = _capture(capsys, root, "install", "--npx", _SPECIFIER, "--yes")

    assert code == 0
    assert f"已安装 {_NPX_PACKAGE}。" in out
    assert "发现的工具：   1 个" in out
    assert 'command = ["npx", "-y", "weather-mcp"]' in (root / _CONFIG).read_text(encoding="utf-8")


def test_uvx_uses_its_own_package_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """两个包管理器取到的是不同的包，注册表里不能混成一个 identity。"""
    _stub(monkeypatch)
    root = _project(tmp_path)

    code, out, _ = _capture(capsys, root, "install", "--uvx", _SPECIFIER, "--yes")

    assert code == 0
    assert _UVX_PACKAGE in out
    assert 'command = ["uvx", "weather-mcp"]' in (root / _CONFIG).read_text(encoding="utf-8")


def test_the_runner_entry_runs_in_the_project_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """不克隆任何东西时，进程的 cwd 与安装根无关，只能是项目根。"""
    _stub(monkeypatch)
    root = _project(tmp_path)

    _capture(capsys, root, "install", "--npx", _SPECIFIER, "--yes")

    assert 'working_dir = "."' in (root / _CONFIG).read_text(encoding="utf-8")


def test_the_plan_shows_a_runner_not_a_repository(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """展示层不能露出这条路径上不存在的字段：没有 ref、没有 commit、没有安装路径。"""
    _stub(monkeypatch)

    _, out, _ = _capture(capsys, _project(tmp_path), "install", "--npx", _SPECIFIER, "--yes")

    assert "Runner:        npx" in out
    assert "Command:       npx -y weather-mcp" in out
    for absent in ("Repository:", "Ref:", "Commit:", "Install path:"):
        assert absent not in out


def test_the_plan_renders_the_registry_entry_it_will_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _stub(monkeypatch)
    root = _project(tmp_path)

    _, out, _ = _capture(capsys, root, "install", "--npx", _SPECIFIER, "--yes")

    displayed = [line.strip() for line in out.splitlines() if " = " in line]
    written = (root / _CONFIG).read_text(encoding="utf-8")
    assert displayed, "计划里应该有注册表条目"
    for line in displayed:
        assert line in written, f"计划展示了注册表里没有的 {line!r}"


def test_nothing_is_cloned_and_no_manifest_is_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """这条路径上既没有仓库也没有清单：包由包管理器自己取。"""
    source, cloner = _stub(monkeypatch)

    code, _, _ = _capture(capsys, _project(tmp_path), "install", "--npx", _SPECIFIER, "--yes")

    assert code == 0
    assert cloner.calls == []
    assert source.calls == []
    assert source.manifest_calls == []
    assert apps_root_entries(tmp_path) == []


def test_an_explicit_package_overrides_the_derived_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _stub(monkeypatch)
    root = _project(tmp_path)

    code, out, _ = _capture(capsys, root, "install", "--npx", _SPECIFIER, "--package", "com.example.weather", "--yes")

    assert code == 0
    assert "com.example.weather" in out
    assert _NPX_PACKAGE not in out


def test_a_disabled_registration_points_at_the_enable_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _stub(monkeypatch)

    _, out, _ = _capture(capsys, _project(tmp_path), "install", "--npx", _SPECIFIER, "--disabled", "--yes")

    assert f"aurora app enable {_NPX_PACKAGE}" in out
    assert f"已登记 {_NPX_PACKAGE}。" in out


def test_enable_writes_enabled_true(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _stub(monkeypatch, factory=_factory())
    root = _project(tmp_path)

    _, out, _ = _capture(capsys, root, "install", "--npx", _SPECIFIER, "--yes")

    assert "enabled = true" in out
    assert "enabled = true" in (root / _CONFIG).read_text(encoding="utf-8")


# --- verify 连的是项目根 ----------------------------------------------------------


def test_verify_starts_the_process_in_the_project_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """这条路径没有 staging，装完即用，没有第二个地方可连。"""
    factory = _factory()
    _stub(monkeypatch, factory=factory)
    root = _project(tmp_path)

    code, out, _ = _capture(capsys, root, "install", "--npx", _SPECIFIER, "--yes")

    assert code == 0
    assert len(factory.specs) == 1
    assert factory.spec().working_dir == root.resolve()
    assert factory.spec().command == ("npx", "-y", "weather-mcp")
    assert "发现的工具：   1 个" in out


def test_a_failed_verification_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """登记前失败：注册表还是原来那份，用户看不到任何残留。"""
    factory = FakeMcpClientFactory(protocol_version=DEFAULT_PROTOCOL, failure=RuntimeError("起不来"))
    _stub(monkeypatch, factory=factory)
    root = _project(tmp_path)

    code, _, err = _capture(capsys, root, "install", "--npx", _SPECIFIER, "--yes")

    assert code == EXIT_FAILURE
    assert "App 操作失败" in err
    assert (root / _CONFIG).read_text(encoding="utf-8") == _EMPTY_REGISTRY


# --- 互斥 -----------------------------------------------------------------------


def test_both_runners_at_once_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _stub(monkeypatch)

    code, _, err = _capture(capsys, _project(tmp_path), "install", "--npx", "a", "--uvx", "b", "--yes")

    assert code == EXIT_CONFIG_ERROR
    assert "--npx 与 --uvx 只能用一个" in err


def test_a_runner_with_a_repository_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """两种取包方式对应两条完全不同的准入规则，混着给说明用户没想清楚要哪一种。"""
    _stub(monkeypatch)

    code, _, err = _capture(capsys, _project(tmp_path), "install", "churk-ben/aurora-qq", "--npx", _SPECIFIER, "--yes")

    assert code == EXIT_CONFIG_ERROR
    assert "--npx 不接受仓库参数" in err


def test_a_runner_with_a_ref_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _stub(monkeypatch)

    code, _, err = _capture(capsys, _project(tmp_path), "install", "--npx", _SPECIFIER, "--ref", "main", "--yes")

    assert code == EXIT_CONFIG_ERROR
    assert "不克隆任何仓库" in err


def test_a_runner_with_a_command_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """``--npx`` 已经决定了启动命令，再给一条没有第二种解释。"""
    _stub(monkeypatch)

    code, _, err = _capture(
        capsys, _project(tmp_path), "install", "--npx", _SPECIFIER, "--command", '["node","x.js"]', "--yes"
    )

    assert code == EXIT_CONFIG_ERROR
    assert "--command" in err


def test_neither_a_repository_nor_a_runner_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    source, _ = _stub(monkeypatch)

    code, _, err = _capture(capsys, _project(tmp_path), "install", "--yes")

    assert code == EXIT_CONFIG_ERROR
    assert "--npx" in err
    assert source.calls == []


# --- 准入与确认 ------------------------------------------------------------------


def test_a_duplicate_package_is_rejected_before_the_question(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _stub(monkeypatch)
    root = _project(tmp_path, registry_entry(_NPX_PACKAGE))

    code, out, err = _capture(capsys, root, "install", "--npx", _SPECIFIER, "--yes")

    assert code == EXIT_CONFIG_ERROR
    assert _NPX_PACKAGE in err
    assert "Runner:" not in out, "查重失败就没有计划可展示"


def test_a_missing_registry_points_at_aurora_setup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _stub(monkeypatch)

    code, _, err = _capture(capsys, tmp_path, "install", "--npx", _SPECIFIER, "--yes")

    assert code == EXIT_CONFIG_ERROR
    assert "aurora setup" in err


def test_an_unsafe_specifier_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """包名会原样进 argv：带空白或路径形状的输入不进计划。"""
    _stub(monkeypatch)

    code, _, err = _capture(capsys, _project(tmp_path), "install", "--npx", "../demo", "--yes")

    assert code == EXIT_CONFIG_ERROR
    assert "App 配置错误" in err


def test_a_refused_confirmation_registers_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _stub(monkeypatch)
    root = _project(tmp_path)
    _terminal(monkeypatch, "n")

    code, out, _ = _capture(capsys, root, "install", "--npx", _SPECIFIER)

    assert code == EXIT_INTERRUPTED
    assert "已取消" in out
    assert (root / _CONFIG).read_text(encoding="utf-8") == _EMPTY_REGISTRY


def test_the_plan_is_shown_before_the_question(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _stub(monkeypatch)
    root = _project(tmp_path)
    _terminal(monkeypatch, "n")

    _, out, _ = _capture(capsys, root, "install", "--npx", _SPECIFIER)

    assert out.index("Runner:") < out.index("Continue?")


def test_a_non_interactive_stdin_without_yes_is_a_config_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _stub(monkeypatch)
    root = _project(tmp_path)
    _pipe(monkeypatch)

    code, _, err = _capture(capsys, root, "install", "--npx", _SPECIFIER)

    assert code == EXIT_CONFIG_ERROR
    assert "--yes" in err

"""``aurora app install <URL>``：把一个已经在运行的远程 MCP 端点写进注册表。

远程安装不下载源码、不读启动清单、不安装依赖，注册表保存端点地址与认证变量名。
这个文件重点验证两类行为：

* 握手是准入门槛 —— ``--yes`` 跳过的是提问，不是它；
* token 的值一次都不落盘、不打印，注册表里存的是变量名。
"""

from __future__ import annotations

import io
import sys
from typing import TYPE_CHECKING

import pytest

from aurora.commander import run
from aurora.commands import DEFAULT_REGISTRY
from aurora.commands.app.verify import MCPVerifier
from aurora.utils.process import EXIT_CONFIG_ERROR, EXIT_FAILURE, EXIT_INTERRUPTED
from tests.app_clone_support import FakeCloner, registry_entry
from tests.app_install_support import ENDPOINT, ENDPOINT_PACKAGE, FakeMcpClientFactory, FakeSource, stub_cli

if TYPE_CHECKING:
    from pathlib import Path

_EMPTY_REGISTRY = "app = []\n"
_CONFIG = "config/apps.toml"
_DEFAULT_PROTOCOL = "2025-06-18"
_TOKEN_NAME = "MCP_TOKEN"
_TOKEN_VALUE = "s3cr3t-value"
_UNSET_NAME = "AURORA_TEST_UNSET_TOKEN"
_BASE = ("install", ENDPOINT, "--package", ENDPOINT_PACKAGE)


def _project(tmp_path: Path, apps_toml: str = _EMPTY_REGISTRY) -> Path:
    config = tmp_path / "config"
    config.mkdir(parents=True, exist_ok=True)
    (config / "apps.toml").write_text(apps_toml, encoding="utf-8")
    return tmp_path


def _capture(capsys: pytest.CaptureFixture[str], root: Path, *arguments: str) -> tuple[int, str, str]:
    code = run(["--root", str(root), "app", *arguments], registry=DEFAULT_REGISTRY)
    streams = capsys.readouterr()
    return code, streams.out, streams.err


def _factory(**kwargs: object) -> FakeMcpClientFactory:
    return FakeMcpClientFactory(protocol_version=_DEFAULT_PROTOCOL, **kwargs)  # type: ignore[arg-type]


def _stub(
    monkeypatch: pytest.MonkeyPatch, *, factory: FakeMcpClientFactory | None = None
) -> tuple[FakeSource, FakeCloner]:
    """装配接缝；不传 factory 时这条路径上一次 MCP 都不连。"""
    return stub_cli(monkeypatch, verifier=None if factory is None else MCPVerifier(factory))


class _Terminal(io.StringIO):
    def isatty(self) -> bool:
        return True


def _terminal(monkeypatch: pytest.MonkeyPatch, answer: str = "n") -> None:
    monkeypatch.setattr(sys, "stdin", _Terminal(f"{answer}\n"))


def _pipe(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "stdin", io.StringIO())


def test_install_remote_registers_the_endpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _stub(monkeypatch, factory=_factory())
    root = _project(tmp_path)

    code, out, _ = _capture(capsys, root, *_BASE, "--yes")

    assert code == 0
    assert f"已安装 {ENDPOINT_PACKAGE}。" in out
    assert "发现的工具：   1 个" in out


def test_the_package_is_derived_from_the_url_when_not_given(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    source, cloner = _stub(monkeypatch, factory=_factory())
    root = _project(tmp_path)

    code, out, _ = _capture(capsys, root, "install", ENDPOINT, "--yes")

    assert code == 0
    assert "已安装 remote.mcp.example.com.rpc。" in out
    assert 'package = "remote.mcp.example.com.rpc"' in (root / _CONFIG).read_text(encoding="utf-8")
    assert source.calls == []
    assert cloner.calls == []


def test_the_written_entry_is_a_streamable_http_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """远程条目走运行时那份白名单：多一个 working_dir 会让 start 拒绝整份注册表。"""
    _stub(monkeypatch, factory=_factory())
    root = _project(tmp_path)

    _capture(capsys, root, *_BASE, "--yes")

    written = (root / _CONFIG).read_text(encoding="utf-8")
    assert "[[app]]" in written
    assert f'package = "{ENDPOINT_PACKAGE}"' in written
    assert 'transport = "streamable_http"' in written
    assert f'url = "{ENDPOINT}"' in written
    assert "enabled = true" in written
    assert "working_dir" not in written
    assert "command" not in written


def test_the_plan_renders_the_registry_entry_it_will_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _stub(monkeypatch, factory=_factory())
    root = _project(tmp_path)

    _, out, _ = _capture(capsys, root, *_BASE, "--yes")

    displayed = [line.strip() for line in out.splitlines() if " = " in line]
    written = (root / _CONFIG).read_text(encoding="utf-8")
    assert displayed, "计划里应该有注册表条目"
    for line in displayed:
        assert line in written, f"计划展示了注册表里没有的 {line!r}"


def test_the_plan_says_verification_is_mandatory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """远程登记必须握手，成功后才能写入注册表。"""
    _stub(monkeypatch, factory=_factory())

    _, out, _ = _capture(capsys, _project(tmp_path), *_BASE, "--yes")

    assert "Verification:  required before registering" in out
    assert "Auth env:      (none)" in out


def test_nothing_is_cloned_and_no_manifest_is_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """远程 Server 的「安装」发生在别人那里，Aurora 只记地址。"""
    source, cloner = _stub(monkeypatch, factory=_factory())

    _capture(capsys, _project(tmp_path), *_BASE, "--yes")

    assert cloner.calls == []
    assert source.calls == []
    assert source.manifest_calls == []


def test_enable_writes_enabled_true(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _stub(monkeypatch, factory=_factory())
    root = _project(tmp_path)

    _, out, _ = _capture(capsys, root, *_BASE, "--yes")

    assert "enabled = true" in out
    assert "enabled = true" in (root / _CONFIG).read_text(encoding="utf-8")


def test_an_enabled_remote_entry_does_not_mention_disabling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _stub(monkeypatch, factory=_factory())

    _, out, _ = _capture(capsys, _project(tmp_path), *_BASE, "--yes")

    assert f"aurora app enable {ENDPOINT_PACKAGE}" not in out


def test_a_disabled_remote_entry_points_at_the_enable_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _stub(monkeypatch, factory=_factory())

    _, out, _ = _capture(capsys, _project(tmp_path), *_BASE, "--disabled", "--yes")

    assert f"aurora app enable {ENDPOINT_PACKAGE}" in out


def test_auth_env_stores_only_the_variable_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """注册表会被读、会被提交、会被贴进 issue：里面只能有变量名。"""
    monkeypatch.setenv(_TOKEN_NAME, _TOKEN_VALUE)
    _stub(monkeypatch, factory=_factory())
    root = _project(tmp_path)

    code, out, _ = _capture(capsys, root, *_BASE, "--auth-env", _TOKEN_NAME, "--yes")

    assert code == 0
    written = (root / _CONFIG).read_text(encoding="utf-8")
    assert f'auth_env = "{_TOKEN_NAME}"' in written
    assert _TOKEN_VALUE not in written
    assert _TOKEN_VALUE not in out


def test_the_plan_shows_the_variable_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv(_TOKEN_NAME, _TOKEN_VALUE)
    _stub(monkeypatch, factory=_factory())

    _, out, _ = _capture(capsys, _project(tmp_path), *_BASE, "--auth-env", _TOKEN_NAME, "--yes")

    assert f"Auth env:      {_TOKEN_NAME}" in out


def test_the_token_reaches_the_handshake(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """只存名字不等于不用它：握手要拿它当 Bearer token 发出去。"""
    monkeypatch.setenv(_TOKEN_NAME, _TOKEN_VALUE)
    factory = _factory()
    _stub(monkeypatch, factory=factory)

    _capture(capsys, _project(tmp_path), *_BASE, "--auth-env", _TOKEN_NAME, "--yes")

    assert factory.spec().auth_token == _TOKEN_VALUE


def test_a_declared_but_unset_variable_fails_before_registering(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """与其发一个必然 401 的请求、把用户引去查网络，不如说清是哪个变量没设置。"""
    factory = _factory()
    _stub(monkeypatch, factory=factory)
    root = _project(tmp_path)

    code, _, err = _capture(capsys, root, *_BASE, "--auth-env", _UNSET_NAME, "--yes")

    assert code == EXIT_CONFIG_ERROR
    assert _UNSET_NAME in err
    assert factory.specs == [], "没拿到 token 就不该发起连接"
    assert (root / _CONFIG).read_text(encoding="utf-8") == _EMPTY_REGISTRY


def test_a_bad_variable_name_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _stub(monkeypatch, factory=_factory())

    code, _, err = _capture(capsys, _project(tmp_path), *_BASE, "--auth-env", "1BAD", "--yes")

    assert code == EXIT_CONFIG_ERROR
    assert "连接配置不合法" in err


def test_the_handshake_runs_before_registering(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """这条路径上 Aurora 没有别的东西能证明这个 URL 后面真的是 MCP。"""
    factory = _factory()
    _stub(monkeypatch, factory=factory)

    _capture(capsys, _project(tmp_path), *_BASE, "--yes")

    assert len(factory.specs) == 1
    assert factory.spec().url == ENDPOINT


def test_a_refused_confirmation_skips_the_handshake(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """确认在握手之前：用户说不要，就没必要再去连一次别人的服务器。"""
    factory = _factory()
    _stub(monkeypatch, factory=factory)
    root = _project(tmp_path)
    _terminal(monkeypatch, "n")

    code, out, _ = _capture(capsys, root, *_BASE)

    assert code == EXIT_INTERRUPTED
    assert "已取消" in out
    assert factory.specs == []
    assert (root / _CONFIG).read_text(encoding="utf-8") == _EMPTY_REGISTRY


def test_the_plan_is_shown_before_the_question(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _stub(monkeypatch, factory=_factory())
    root = _project(tmp_path)
    _terminal(monkeypatch, "n")

    _, out, _ = _capture(capsys, root, *_BASE)

    assert out.index("URL:") < out.index("Continue?")


def test_a_failed_handshake_leaves_the_registry_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _stub(monkeypatch, factory=_factory(failure=RuntimeError("connection refused")))
    root = _project(tmp_path)

    code, _, err = _capture(capsys, root, *_BASE, "--yes")

    assert code == EXIT_FAILURE
    assert "App 操作失败" in err
    assert (root / _CONFIG).read_text(encoding="utf-8") == _EMPTY_REGISTRY


def test_the_handshake_failure_names_the_remote_subject(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """本地进程与远程端点的排错方向完全不同，消息里必须说清是哪一种。"""
    _stub(monkeypatch, factory=_factory(failure=RuntimeError("connection refused")))

    _, _, err = _capture(capsys, _project(tmp_path), *_BASE, "--yes")

    assert "远程 MCP 端点" in err


@pytest.mark.parametrize(
    "url",
    [
        "http://mcp.example.com/rpc",
        "https://user:pw@mcp.example.com/rpc",
        f"{ENDPOINT}?token=abc",
        f"{ENDPOINT}?api_key=abc",
    ],
)
def test_a_url_that_cannot_be_registered_is_rejected_before_connecting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], url: str
) -> None:
    """URL 会进注册表、会被日志回显，所以凭据形状的地址在连接之前就该被挡下。"""
    factory = _factory()
    _stub(monkeypatch, factory=factory)
    root = _project(tmp_path)

    code, _, err = _capture(capsys, root, "install", url, "--package", ENDPOINT_PACKAGE, "--yes")

    assert code == EXIT_CONFIG_ERROR
    assert "App 配置错误" in err
    assert factory.specs == []
    assert (root / _CONFIG).read_text(encoding="utf-8") == _EMPTY_REGISTRY


def test_a_bad_package_id_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _stub(monkeypatch, factory=_factory())

    code, _, err = _capture(capsys, _project(tmp_path), "install", ENDPOINT, "--package", "Not.A.Package", "--yes")

    assert code == EXIT_CONFIG_ERROR
    assert "--package" in err
    assert "小写点分包名" in err


def test_a_duplicate_package_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _stub(monkeypatch, factory=_factory())
    root = _project(tmp_path, registry_entry(ENDPOINT_PACKAGE))

    code, _, err = _capture(capsys, root, *_BASE, "--yes")

    assert code == EXIT_CONFIG_ERROR
    assert ENDPOINT_PACKAGE in err


def test_the_duplicate_check_runs_before_the_handshake(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """重复的 package 无论端点通不通都不该写进去，那就别先去连一次。"""
    factory = _factory()
    _stub(monkeypatch, factory=factory)
    root = _project(tmp_path, registry_entry(ENDPOINT_PACKAGE))

    _capture(capsys, root, *_BASE, "--yes")

    assert factory.specs == []


def test_a_missing_registry_points_at_aurora_setup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    factory = _factory()
    _stub(monkeypatch, factory=factory)

    code, _, err = _capture(capsys, tmp_path, *_BASE, "--yes")

    assert code == EXIT_CONFIG_ERROR
    assert "aurora setup" in err
    assert factory.specs == [], "连不上注册表就不必去连端点"


def test_a_non_interactive_stdin_without_yes_is_a_config_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    factory = _factory()
    _stub(monkeypatch, factory=factory)
    root = _project(tmp_path)
    _pipe(monkeypatch)

    code, _, err = _capture(capsys, root, *_BASE)

    assert code == EXIT_CONFIG_ERROR
    assert "--yes" in err
    assert factory.specs == []
    assert (root / _CONFIG).read_text(encoding="utf-8") == _EMPTY_REGISTRY

"""``aurora app search`` 的命令装配、参数转发、退出码与工厂测试。

这里只管「命令怎么搭起来、参数怎么送进去、出错怎么回话」；结果长什么样归
``test_app_search_render.py``。全部离线：要么整体替换 ``_github_source``，要么
把真实 GitHubSource 的出口换成假 transport。两条路都不发请求。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx2
import pytest
from app_search_support import FakeTransport, captured, cli, page, repository, stub, use_fake_transport

from aurora.commander import run
from aurora.commands import DEFAULT_REGISTRY
from aurora.commands import app as app_module
from aurora.commands.app.models import DiscoveryError
from aurora.utils.process import EXIT_CONFIG_ERROR, EXIT_FAILURE

if TYPE_CHECKING:
    from pathlib import Path

_TOKEN = "ghp_SECRETTOKEN123"
_CONFIG = "config/apps.toml"


# --- 命令注册 -----------------------------------------------------------------


def test_help_lists_the_search_subcommand(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        run(["app", "--help"], registry=DEFAULT_REGISTRY)

    assert exit_info.value.code == 0
    assert "search" in " ".join(capsys.readouterr().out.split())


def test_search_help_lists_its_options(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        run(["app", "search", "--help"], registry=DEFAULT_REGISTRY)

    assert exit_info.value.code == 0
    usage = " ".join(capsys.readouterr().out.split())
    for option in ("--page", "--page-size", "--sort", "--order", "--json"):
        assert option in usage


# --- 与注册表无关 ----------------------------------------------------------------


def test_search_works_without_a_registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """search 与 config/apps.toml 无关：注册表不存在也照样搜索。"""
    source = stub(monkeypatch, page((repository(),)))

    assert cli(tmp_path, "search") == 0

    assert len(source.calls) == 1
    assert not (tmp_path / _CONFIG).exists()


def test_search_never_creates_the_registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    stub(monkeypatch, page((repository(),)))

    assert cli(tmp_path, "search") == 0

    assert not (tmp_path / "config").exists()


# --- 参数转发 -----------------------------------------------------------------


def test_defaults_are_forwarded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = stub(monkeypatch, page())

    assert cli(tmp_path, "search") == 0

    assert source.calls == [{"query": None, "page": 1, "page_size": 20, "sort": None, "order": None}]


@pytest.mark.parametrize(
    ("arguments", "expected"),
    [
        (("search", "weather"), {"query": "weather"}),
        (("search", "--page", "3"), {"page": 3}),
        (("search", "--page-size", "5"), {"page_size": 5}),
        (("search", "--sort", "stars"), {"sort": "stars"}),
        (("search", "--sort", "stars", "--order", "asc"), {"sort": "stars", "order": "asc"}),
    ],
)
def test_arguments_are_forwarded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, arguments: tuple[str, ...], expected: dict[str, object]
) -> None:
    source = stub(monkeypatch, page())

    assert cli(tmp_path, *arguments) == 0

    assert {key: source.calls[0][key] for key in expected} == expected


# --- 失败路径 -----------------------------------------------------------------


def test_a_discovery_failure_is_a_general_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    stub(monkeypatch, DiscoveryError("GitHub API 配额已耗尽"))

    code, output, error = captured(capsys, tmp_path, "search")

    assert code == EXIT_FAILURE
    assert "App 搜索失败：GitHub API 配额已耗尽" in error
    assert output == ""


def test_an_out_of_range_page_is_a_configuration_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """参数问题在发请求前就被拒；退出码 2 表示「你的输入不对」。"""
    transport = use_fake_transport(monkeypatch)

    code, output, error = captured(capsys, tmp_path, "search", "--page", "0")

    assert code == EXIT_CONFIG_ERROR
    assert "App 配置错误" in error
    assert "--page" in error
    assert output == ""
    assert transport.calls == []


def test_an_unknown_sort_field_is_a_configuration_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    transport = use_fake_transport(monkeypatch)

    code, _, error = captured(capsys, tmp_path, "search", "--sort", "name")

    assert code == EXIT_CONFIG_ERROR
    assert "--sort" in error
    assert transport.calls == []


def test_a_page_beyond_the_search_window_is_a_configuration_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    transport = use_fake_transport(monkeypatch)

    code, _, error = captured(capsys, tmp_path, "search", "--page", "999")

    assert code == EXIT_CONFIG_ERROR
    assert "1000" in error
    assert transport.calls == []


def test_a_transport_failure_is_reported_without_a_traceback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    use_fake_transport(monkeypatch, httpx2.ConnectError("boom"))

    code, _, error = captured(capsys, tmp_path, "search")

    assert code == EXIT_FAILURE
    assert "Traceback" not in error
    assert "ConnectError" in error


def test_a_failed_search_never_prints_the_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """提示里出现的是变量名；token 的值绝不能进终端。"""
    use_fake_transport(monkeypatch, httpx2.Response(401, json={"message": "Bad credentials"}))
    monkeypatch.setenv("GITHUB_TOKEN", _TOKEN)

    code, output, error = captured(capsys, tmp_path, "search")

    assert code == EXIT_FAILURE
    assert _TOKEN not in error
    assert _TOKEN not in output
    assert "GITHUB_TOKEN" in error


# --- 环境载入与工厂组装 ---------------------------------------------------------


@pytest.mark.parametrize("arguments", [("list",), ("search",), ("enable", "com.example.weather")])
def test_the_project_env_is_loaded_for_every_subcommand(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, arguments: tuple[str, ...]
) -> None:
    """与 aurora start 同一惯例：命令入口先载入 .env，而不是只有 search 才载。

    这样「app 会读项目 .env」是一条可解释的规则，而不是某个子命令的特例。
    """
    (tmp_path / "config").mkdir()
    (tmp_path / _CONFIG).write_text('[[app]]\npackage = "com.example.weather"\nenabled = false\n', encoding="utf-8")
    seen: list[Path] = []
    monkeypatch.setattr(app_module, "load_project_env", seen.append)
    stub(monkeypatch, page())

    cli(tmp_path, *arguments)

    assert seen == [tmp_path]


def test_a_broken_project_env_is_a_configuration_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """载入失败包成 ConfigError：走既有错误通道，不退化成 traceback。"""

    def explode(root: Path) -> None:
        raise OSError("bad env file")

    monkeypatch.setattr(app_module, "load_project_env", explode)

    code, output, error = captured(capsys, tmp_path, "list")

    assert code == EXIT_CONFIG_ERROR
    assert "App 配置错误" in error
    assert ".env" in error
    assert "Traceback" not in error
    assert output == ""


def test_the_factory_passes_the_environment_token_to_the_source(monkeypatch: pytest.MonkeyPatch) -> None:
    transport = FakeTransport()
    monkeypatch.setattr(app_module, "HttpxTransport", lambda: transport)
    monkeypatch.setenv("GITHUB_TOKEN", _TOKEN)

    app_module._github_source().search()

    assert transport.calls[0]["headers"]["Authorization"] == f"Bearer {_TOKEN}"


def test_the_factory_omits_authorization_without_a_token(monkeypatch: pytest.MonkeyPatch) -> None:
    transport = FakeTransport()
    monkeypatch.setattr(app_module, "HttpxTransport", lambda: transport)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)

    app_module._github_source().search()

    assert "Authorization" not in transport.calls[0]["headers"]

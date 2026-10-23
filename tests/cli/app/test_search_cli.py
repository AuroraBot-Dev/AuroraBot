"""离线验证搜索入口、无副作用读取、错误传播与凭据边界。"""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx2
import pytest

from aurora_cli.commands import app as app_module
from aurora_cli.commands.app.models import DiscoveryError
from aurora_cli.utils.process import EXIT_CONFIG_ERROR, EXIT_FAILURE
from tests.cli.app.search_support import FakeTransport, captured, cli, page, repository, stub, use_fake_transport

if TYPE_CHECKING:
    from pathlib import Path

_TOKEN = "ghp_SECRETTOKEN123"
_CONFIG = "config/apps.toml"


def test_search_works_without_a_registry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """search 与 config/apps.toml 无关：注册表不存在也照样搜索。"""
    source = stub(monkeypatch, page((repository(),)))

    assert cli(tmp_path, "search") == 0

    assert source.calls == [{"query": None, "page": 1, "page_size": 20, "sort": None, "order": None}]
    assert not (tmp_path / "config").exists()
    assert "Churk-Ben/Aurora-QQ" in capsys.readouterr().out


def test_arguments_are_forwarded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = stub(monkeypatch, page())

    assert (
        cli(tmp_path, "search", "weather", "--page", "3", "--page-size", "5", "--sort", "stars", "--order", "asc") == 0
    )
    assert source.calls == [{"query": "weather", "page": 3, "page_size": 5, "sort": "stars", "order": "asc"}]


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


def test_an_empty_result_is_not_an_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    stub(monkeypatch, page())

    code, output, error = captured(capsys, tmp_path, "search")

    assert code == 0
    assert "没有找到带 aurorabot-app topic 的仓库" in output
    assert error == ""


def test_incomplete_results_warn_on_stderr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """结果不完整仍然可用，所以不动退出码，但要说清可能还有仓库。"""
    stub(monkeypatch, page((repository(),), incomplete_results=True))

    code, _, error = captured(capsys, tmp_path, "search")

    assert code == 0
    assert "搜索结果不完整" in error

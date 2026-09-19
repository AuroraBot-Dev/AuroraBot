"""``aurora app search`` 的命令注册、表格渲染、JSON 与失败路径测试。

全部离线：要么整体替换 ``_github_source``，要么把真实 GitHubSource 的出口
换成假 transport。两条路都不发请求。
"""

from __future__ import annotations

import json
import unicodedata
from typing import TYPE_CHECKING, Any

import httpx2
import pytest

from aurora.commander import build_parser, run
from aurora.commands import DEFAULT_REGISTRY
from aurora.commands import app as app_module
from aurora.commands.app.models import DiscoveryError, Repository, RepositoryPage
from aurora.utils.process import EXIT_CONFIG_ERROR, EXIT_FAILURE

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

_TOKEN = "ghp_SECRETTOKEN123"
_CONFIG = "config/apps.toml"
_HEADERS = ["REPOSITORY", "STARS", "STATUS", "UPDATED", "DESCRIPTION"]
_SEPARATOR_PREFIX = "|="
_FULLWIDTH = frozenset(("F", "W"))
_DESCRIPTION_WIDTH = 50


class _FakeTransport:
    """替掉 HTTP 层；返回预置响应（或抛出预置异常）并记录每次请求。"""

    def __init__(self, *responses: httpx2.Response | Exception) -> None:
        self.responses = list(responses) or [_empty_response()]
        self.calls: list[dict[str, Any]] = []

    def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        params: Mapping[str, str | int],
        timeout: float,
    ) -> httpx2.Response:
        self.calls.append({"url": url, "headers": headers, "params": params, "timeout": timeout})
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class _StubSource:
    """替掉整个 GitHub 路径；只记录参数并返回预置页。"""

    def __init__(self, result: RepositoryPage | Exception) -> None:
        self.result = result
        self.calls: list[dict[str, object]] = []

    def search(
        self,
        query: str | None = None,
        *,
        page: int = 1,
        page_size: int = 20,
        sort: str | None = None,
        order: str | None = None,
    ) -> RepositoryPage:
        self.calls.append({"query": query, "page": page, "page_size": page_size, "sort": sort, "order": order})
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def _empty_response() -> httpx2.Response:
    return httpx2.Response(200, json={"total_count": 0, "incomplete_results": False, "items": []})


@pytest.fixture
def http(monkeypatch: pytest.MonkeyPatch) -> _FakeTransport:
    """让真实 GitHubSource 走假 transport，并清掉环境里的 token。"""
    transport = _FakeTransport()
    monkeypatch.setattr(app_module, "load_project_env", lambda root: None)
    monkeypatch.setattr(app_module, "HttpxTransport", lambda: transport)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    return transport


def _repo(**overrides: object) -> Repository:
    fields: dict[str, Any] = {
        "full_name": "Churk-Ben/Aurora-QQ",
        "owner": "Churk-Ben",
        "name": "Aurora-QQ",
        "description": "QQ 通知 App",
        "stars": 12,
        "topics": ("aurorabot-app",),
        "updated_at": "2026-09-01T12:00:00Z",
        "default_branch": "main",
        "html_url": "https://github.com/Churk-Ben/Aurora-QQ",
        "clone_url": "https://github.com/Churk-Ben/Aurora-QQ.git",
        "archived": False,
        "disabled": False,
    }
    fields.update(overrides)
    return Repository(**fields)


def _page(items: tuple[Repository, ...] = (), **overrides: object) -> RepositoryPage:
    fields: dict[str, Any] = {
        "items": items,
        "page": 1,
        "page_size": 20,
        "total_count": len(items),
        "incomplete_results": False,
    }
    fields.update(overrides)
    return RepositoryPage(**fields)


def _stub(monkeypatch: pytest.MonkeyPatch, result: RepositoryPage | Exception) -> _StubSource:
    source = _StubSource(result)
    monkeypatch.setattr(app_module, "_github_source", lambda: source)
    return source


def _cli(root: Path, *arguments: str) -> int:
    """借真实解析器造出 Namespace 再调 execute；参数解析必须是真的。"""
    namespace = build_parser(DEFAULT_REGISTRY).parse_args(["--root", str(root), "app", *arguments])
    return app_module.execute(namespace)


def _captured(capsys: pytest.CaptureFixture[str], root: Path, *arguments: str) -> tuple[int, str, str]:
    code = _cli(root, *arguments)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


# --- 表格解析（自带一份，不复用其它测试模块的私有辅助） -----------------------


def _cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip("|").split("|")]


def _separator_index(output: str) -> int:
    return next(index for index, line in enumerate(output.splitlines()) if line.startswith(_SEPARATOR_PREFIX))


def _header_row(output: str) -> list[str]:
    return _cells(output.splitlines()[_separator_index(output) - 1])


def _data_rows(output: str) -> list[list[str]]:
    lines = output.splitlines()
    return [_cells(line) for line in lines[_separator_index(output) + 1 :] if line.startswith("| ")]


def _cell_width(text: str) -> int:
    return sum(2 if unicodedata.east_asian_width(char) in _FULLWIDTH else 1 for char in text)


def _widths(output: str) -> set[int]:
    """只量框线行 —— 表格下方还有一行普通文本的页脚。"""
    return {_cell_width(line) for line in output.splitlines() if line[:1] in ("+", "|")}


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
    source = _stub(monkeypatch, _page((_repo(),)))

    assert _cli(tmp_path, "search") == 0

    assert len(source.calls) == 1
    assert not (tmp_path / _CONFIG).exists()


def test_search_never_creates_the_registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _stub(monkeypatch, _page((_repo(),)))

    assert _cli(tmp_path, "search") == 0

    assert not (tmp_path / "config").exists()


# --- 参数转发 -----------------------------------------------------------------


def test_defaults_are_forwarded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = _stub(monkeypatch, _page())

    assert _cli(tmp_path, "search") == 0

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
    source = _stub(monkeypatch, _page())

    assert _cli(tmp_path, *arguments) == 0

    assert {key: source.calls[0][key] for key in expected} == expected


# --- 表格渲染 -----------------------------------------------------------------


def test_the_table_renders_the_search_columns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _stub(monkeypatch, _page((_repo(),)))

    code, output, _ = _captured(capsys, tmp_path, "search")

    assert code == 0
    assert _header_row(output) == _HEADERS


def test_the_banner_names_the_topic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _stub(monkeypatch, _page((_repo(),)))

    _, output, _ = _captured(capsys, tmp_path, "search")

    assert "topic:aurorabot-app" in output.splitlines()[1]


def test_each_row_projects_one_repository(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _stub(monkeypatch, _page((_repo(), _repo(full_name="aurora/clock", stars=3, archived=True))))

    _, output, _ = _captured(capsys, tmp_path, "search")

    assert _data_rows(output) == [
        ["Churk-Ben/Aurora-QQ", "12", "active", "2026-09-01", "QQ 通知 App"],
        ["aurora/clock", "3", "archived", "2026-09-01", "QQ 通知 App"],
    ]


def test_a_disabled_repository_is_labelled_disabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _stub(monkeypatch, _page((_repo(disabled=True),)))

    _, output, _ = _captured(capsys, tmp_path, "search")

    assert _data_rows(output)[0][2] == "disabled"


def test_missing_description_and_timestamp_render_as_dashes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _stub(monkeypatch, _page((_repo(description=None, updated_at=""),)))

    _, output, _ = _captured(capsys, tmp_path, "search")

    assert _data_rows(output)[0][3:] == ["-", "-"]


def test_a_long_description_is_truncated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _stub(monkeypatch, _page((_repo(description="x" * 200),)))

    _, output, _ = _captured(capsys, tmp_path, "search")

    description = _data_rows(output)[0][4]
    assert len(description) == _DESCRIPTION_WIDTH
    assert description.endswith("…")


def test_a_cjk_description_is_truncated_by_display_width(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """按字符数截断会让中文描述占两倍列宽；这里必须按显示宽度算。"""
    _stub(monkeypatch, _page((_repo(description="描" * 200),)))

    _, output, _ = _captured(capsys, tmp_path, "search")

    description = _data_rows(output)[0][4]
    assert _cell_width(description) <= _DESCRIPTION_WIDTH
    assert description.endswith("…")


def test_every_frame_line_renders_to_the_same_width(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _stub(monkeypatch, _page((_repo(), _repo(full_name="aurora/clock", description="中文描述" * 20))))

    _, output, _ = _captured(capsys, tmp_path, "search")

    assert len(_widths(output)) == 1


def test_the_footer_reports_the_range_and_the_total(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _stub(monkeypatch, _page((_repo(), _repo(), _repo()), page=2, page_size=20, total_count=100))

    _, output, _ = _captured(capsys, tmp_path, "search", "--page", "2")

    assert "显示第 21-23 条，共 100 条。" in output


def test_the_footer_warns_when_the_total_exceeds_the_search_window(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """GitHub 只暴露前 1000 条：用户看不到第 1001 条，得当场告知。"""
    _stub(monkeypatch, _page((_repo(),), total_count=5000))

    _, output, _ = _captured(capsys, tmp_path, "search")

    assert "只暴露前 1000 条" in output


def test_an_empty_result_is_not_an_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _stub(monkeypatch, _page())

    code, output, error = _captured(capsys, tmp_path, "search")

    assert code == 0
    assert "没有找到带 aurorabot-app topic 的仓库" in output
    assert error == ""


# --- JSON 输出 -----------------------------------------------------------------


def test_json_is_the_only_thing_on_stdout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _stub(monkeypatch, _page((_repo(),)))

    code, output, _ = _captured(capsys, tmp_path, "search", "--json")

    assert code == 0
    assert json.loads(output) == {
        "total_count": 1,
        "page": 1,
        "page_size": 20,
        "incomplete_results": False,
        "items": [
            {
                "full_name": "Churk-Ben/Aurora-QQ",
                "owner": "Churk-Ben",
                "name": "Aurora-QQ",
                "description": "QQ 通知 App",
                "stars": 12,
                "topics": ["aurorabot-app"],
                "updated_at": "2026-09-01T12:00:00Z",
                "default_branch": "main",
                "html_url": "https://github.com/Churk-Ben/Aurora-QQ",
                "clone_url": "https://github.com/Churk-Ben/Aurora-QQ.git",
                "archived": False,
                "disabled": False,
                "status": "active",
            }
        ],
    }


def test_json_carries_the_pagination_it_was_asked_for(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """分页信息是「这一页」的属性；脚本据此才知道还有没有下一页。"""
    _stub(monkeypatch, _page((_repo(),), page=3, page_size=5, total_count=1500))

    _, output, _ = _captured(capsys, tmp_path, "search", "--json")

    payload = json.loads(output)
    assert (payload["page"], payload["page_size"], payload["total_count"]) == (3, 5, 1500)


def test_json_and_table_render_the_same_repositories(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    page = _page((_repo(), _repo(full_name="aurora/clock", archived=True)))
    _stub(monkeypatch, page)
    _, table_output, _ = _captured(capsys, tmp_path, "search")
    _stub(monkeypatch, page)
    _, json_output, _ = _captured(capsys, tmp_path, "search", "--json")

    items = json.loads(json_output)["items"]

    assert [[item["full_name"], item["status"]] for item in items] == [
        [row[0], row[2]] for row in _data_rows(table_output)
    ]


def test_incomplete_results_warn_on_stderr_in_table_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """结果不完整仍然可用，所以不动退出码，但要说清可能还有仓库。"""
    _stub(monkeypatch, _page((_repo(),), incomplete_results=True))

    code, _, error = _captured(capsys, tmp_path, "search")

    assert code == 0
    assert "搜索结果不完整" in error


def test_incomplete_results_are_visible_to_scripts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """stderr 不是给机器的接口：这个信号必须在 JSON 里，否则脚本永远读不到。"""
    _stub(monkeypatch, _page((_repo(),), incomplete_results=True))

    _, output, error = _captured(capsys, tmp_path, "search", "--json")

    assert json.loads(output)["incomplete_results"] is True
    assert error == ""


def test_a_complete_result_is_silent_on_stderr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _stub(monkeypatch, _page((_repo(),)))

    _, _, error = _captured(capsys, tmp_path, "search")

    assert error == ""


# --- 失败路径 -----------------------------------------------------------------


def test_a_discovery_failure_is_a_general_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _stub(monkeypatch, DiscoveryError("GitHub API 配额已耗尽"))

    code, output, error = _captured(capsys, tmp_path, "search")

    assert code == EXIT_FAILURE
    assert "App 搜索失败：GitHub API 配额已耗尽" in error
    assert output == ""


def test_an_out_of_range_page_is_a_configuration_error(
    tmp_path: Path, http: _FakeTransport, capsys: pytest.CaptureFixture[str]
) -> None:
    """参数问题在发请求前就被拒；退出码 2 表示「你的输入不对」。"""
    code, output, error = _captured(capsys, tmp_path, "search", "--page", "0")

    assert code == EXIT_CONFIG_ERROR
    assert "App 配置错误" in error
    assert "--page" in error
    assert output == ""
    assert http.calls == []


def test_an_unknown_sort_field_is_a_configuration_error(
    tmp_path: Path, http: _FakeTransport, capsys: pytest.CaptureFixture[str]
) -> None:
    code, _, error = _captured(capsys, tmp_path, "search", "--sort", "name")

    assert code == EXIT_CONFIG_ERROR
    assert "--sort" in error
    assert http.calls == []


def test_a_page_beyond_the_search_window_is_a_configuration_error(
    tmp_path: Path, http: _FakeTransport, capsys: pytest.CaptureFixture[str]
) -> None:
    code, _, error = _captured(capsys, tmp_path, "search", "--page", "999")

    assert code == EXIT_CONFIG_ERROR
    assert "1000" in error
    assert http.calls == []


def test_a_transport_failure_is_reported_without_a_traceback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(app_module, "load_project_env", lambda root: None)
    monkeypatch.setattr(app_module, "HttpxTransport", lambda: _FakeTransport(httpx2.ConnectError("boom")))
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)

    code, _, error = _captured(capsys, tmp_path, "search")

    assert code == EXIT_FAILURE
    assert "Traceback" not in error
    assert "ConnectError" in error


def test_a_failed_search_never_prints_the_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """提示里出现的是变量名；token 的值绝不能进终端。"""
    monkeypatch.setattr(app_module, "load_project_env", lambda root: None)
    monkeypatch.setattr(
        app_module,
        "HttpxTransport",
        lambda: _FakeTransport(httpx2.Response(401, json={"message": "Bad credentials"})),
    )
    monkeypatch.setenv("GITHUB_TOKEN", _TOKEN)

    code, output, error = _captured(capsys, tmp_path, "search")

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
    _stub(monkeypatch, _page())

    _cli(tmp_path, *arguments)

    assert seen == [tmp_path]


def test_a_broken_project_env_is_a_configuration_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """载入失败包成 ConfigError：走既有错误通道，不退化成 traceback。"""

    def explode(root: Path) -> None:
        raise OSError("bad env file")

    monkeypatch.setattr(app_module, "load_project_env", explode)

    code, output, error = _captured(capsys, tmp_path, "list")

    assert code == EXIT_CONFIG_ERROR
    assert "App 配置错误" in error
    assert ".env" in error
    assert "Traceback" not in error
    assert output == ""


def test_the_factory_passes_the_environment_token_to_the_source(monkeypatch: pytest.MonkeyPatch) -> None:
    transport = _FakeTransport()
    monkeypatch.setattr(app_module, "HttpxTransport", lambda: transport)
    monkeypatch.setenv("GITHUB_TOKEN", _TOKEN)

    app_module._github_source().search()

    assert transport.calls[0]["headers"]["Authorization"] == f"Bearer {_TOKEN}"


def test_the_factory_omits_authorization_without_a_token(monkeypatch: pytest.MonkeyPatch) -> None:
    transport = _FakeTransport()
    monkeypatch.setattr(app_module, "HttpxTransport", lambda: transport)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)

    app_module._github_source().search()

    assert "Authorization" not in transport.calls[0]["headers"]

"""``aurora app search`` 测试的共享辅助：假 GitHub 层、值对象工厂、CLI 入口。

三个 search 测试模块共用这一份，免得每个文件各养一套同名私有辅助。文件名不以
``test_`` 开头，pytest 不会收集它，覆盖率也只统计 ``aurora_cli`` 与 ``aurora_bot``。

假 GitHub 层有两级：``StubSource`` 把整条网络路径换成预置结果，``FakeTransport``
则保留真实的 ``GitHubSource``、只换掉发请求那一步——后者用来验证「线真的接上了」。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import httpx2

from aurora_cli.commander import build_parser
from aurora_cli.commands import app as app_module
from aurora_cli.commands.app.models import Repository, RepositoryPage
from aurora_cli.plugins.catalog import load_plugins

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    import pytest


def empty_response() -> httpx2.Response:
    """一份合法的零结果响应。"""
    return httpx2.Response(200, json={"total_count": 0, "incomplete_results": False, "items": []})


class FakeTransport:
    """替掉 HTTP 层；返回预置响应（或抛出预置异常）并记录每次请求。"""

    def __init__(self, *responses: httpx2.Response | Exception) -> None:
        self.responses = list(responses) or [empty_response()]
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


def use_fake_transport(monkeypatch: pytest.MonkeyPatch, *responses: httpx2.Response | Exception) -> FakeTransport:
    """让真实 ``GitHubSource`` 走假 transport，并清掉环境里的 token。

    写成函数而不是 fixture：fixture 只能活在测试模块或 conftest 里，而这两处
    都不该放只有部分用例需要的东西。
    """
    transport = FakeTransport(*responses)
    monkeypatch.setattr(app_module, "load_project_env", lambda root: None)
    monkeypatch.setattr(app_module, "HttpxTransport", lambda: transport)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    return transport


class StubSource:
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


def stub(monkeypatch: pytest.MonkeyPatch, result: RepositoryPage | Exception) -> StubSource:
    """把 ``_github_source`` 工厂换成预置 source，并把它还给调用方查参数。"""
    source = StubSource(result)
    monkeypatch.setattr(app_module, "_github_source", lambda: source)
    return source


def repository(**overrides: object) -> Repository:
    """一个有内容的仓库；字段可逐个覆盖。"""
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


def page(items: tuple[Repository, ...] = (), **overrides: object) -> RepositoryPage:
    """一页搜索结果；``total_count`` 默认取条目数，可单独覆盖。"""
    fields: dict[str, Any] = {
        "items": items,
        "page": 1,
        "page_size": 20,
        "total_count": len(items),
        "incomplete_results": False,
    }
    fields.update(overrides)
    return RepositoryPage(**fields)


def cli(root: Path, *arguments: str) -> int:
    """借真实解析器造出 Namespace 再调 execute；参数解析必须是真的。"""
    namespace = build_parser(load_plugins(root).registry()).parse_args(["--root", str(root), "app", *arguments])
    return app_module.execute(namespace)


def captured(capsys: pytest.CaptureFixture[str], root: Path, *arguments: str) -> tuple[int, str, str]:
    """跑一次命令，返回退出码与两个输出流。"""
    code = cli(root, *arguments)
    streams = capsys.readouterr()
    return code, streams.out, streams.err

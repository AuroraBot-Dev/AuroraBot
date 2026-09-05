"""GitHub App 目录客户端的离线行为测试。"""

from __future__ import annotations

import io
from http.client import HTTPMessage
from typing import TYPE_CHECKING, Any
from urllib.error import HTTPError, URLError
from urllib.request import Request

import pytest

from aurora.apps import github as github_module
from aurora.apps.github import GitHubClient, JsonResponse
from aurora.apps.models import AppManagerError, normalize_repository

if TYPE_CHECKING:
    from collections.abc import Mapping

_EXPECTED_STARS = 42


def _repository_payload() -> dict[str, object]:
    return {
        "full_name": "AuroraBot-Dev/Weather-App",
        "description": "天气 App",
        "stargazers_count": 42,
        "default_branch": "main",
        "html_url": "https://github.com/AuroraBot-Dev/Weather-App",
        "clone_url": "https://github.com/AuroraBot-Dev/Weather-App.git",
        "topics": ["aurorabot-app"],
        "archived": False,
        "disabled": False,
        "updated_at": "2026-09-01T00:00:00Z",
    }


def test_search_combines_required_topic_and_all_page_options() -> None:
    calls: list[tuple[str, Mapping[str, str]]] = []

    def transport(url: str, headers: Mapping[str, str]) -> JsonResponse:
        calls.append((url, headers))
        return JsonResponse(
            {"total_count": 1, "incomplete_results": True, "items": [_repository_payload()]},
            {},
        )

    result = GitHubClient(token="secret", transport=transport).search(
        query="weather language:python",
        page=3,
        page_size=7,
        sort="updated",
        order="asc",
    )

    assert (result.total, result.page, result.page_size, result.incomplete) == (1, 3, 7, True)
    assert result.repositories[0].full_name == "AuroraBot-Dev/Weather-App"
    url, headers = calls[0]
    assert "q=topic%3Aaurorabot-app+weather+language%3Apython" in url
    assert "page=3" in url and "per_page=7" in url and "sort=updated" in url and "order=asc" in url
    assert headers["Authorization"] == "Bearer secret"
    assert headers["X-GitHub-Api-Version"] == "2022-11-28"


def test_search_without_token_or_query() -> None:
    calls: list[tuple[str, Mapping[str, str]]] = []

    def transport(url: str, headers: Mapping[str, str]) -> JsonResponse:
        calls.append((url, headers))
        return JsonResponse({"total_count": 0, "incomplete_results": False, "items": []}, {})

    result = GitHubClient(transport=transport).search()

    assert result.repositories == ()
    assert "q=topic%3Aaurorabot-app" in calls[0][0]
    assert "Authorization" not in calls[0][1]


@pytest.mark.parametrize(
    ("arguments", "message"),
    (
        ({"page": 0}, "page"),
        ({"page_size": 0}, "page-size"),
        ({"page_size": 101}, "page-size"),
        ({"page": 11, "page_size": 100}, "1000"),
        ({"sort": "forks"}, "sort"),
        ({"order": "sideways"}, "order"),
    ),
)
def test_search_rejects_invalid_options(arguments: dict[str, Any], message: str) -> None:
    with pytest.raises(AppManagerError, match=message):
        GitHubClient(transport=lambda _url, _headers: JsonResponse({}, {})).search(**arguments)


def test_repository_reads_canonical_metadata() -> None:
    client = GitHubClient(transport=lambda _url, _headers: JsonResponse(_repository_payload(), {}))

    repository = client.repository("https://github.com/AuroraBot-Dev/Weather-App.git")

    assert repository.topics == ("aurorabot-app",)
    assert repository.stars == _EXPECTED_STARS
    assert repository.archived is False


@pytest.mark.parametrize(
    "payload",
    (
        {},
        {**_repository_payload(), "topics": "aurorabot-app"},
        {**_repository_payload(), "archived": "false"},
        {**_repository_payload(), "stargazers_count": -1},
        {**_repository_payload(), "updated_at": ""},
    ),
)
def test_repository_rejects_malformed_github_payload(payload: dict[str, object]) -> None:
    client = GitHubClient(transport=lambda _url, _headers: JsonResponse(payload, {}))

    with pytest.raises(AppManagerError, match="GitHub"):
        client.repository("AuroraBot-Dev/Weather-App")


def test_search_rejects_missing_items() -> None:
    client = GitHubClient(
        transport=lambda _url, _headers: JsonResponse(
            {"total_count": 0, "incomplete_results": False},
            {},
        )
    )

    with pytest.raises(AppManagerError, match="items"):
        client.search()


@pytest.mark.parametrize(
    ("source", "expected"),
    (
        ("owner/repo", "owner/repo"),
        ("https://github.com/Owner/Repo", "Owner/Repo"),
        ("https://github.com/Owner/Repo.git/", "Owner/Repo"),
    ),
)
def test_normalize_repository_accepts_supported_forms(source: str, expected: str) -> None:
    assert normalize_repository(source) == expected


@pytest.mark.parametrize("source", ("repo", "git@github.com:owner/repo.git", "https://example.com/owner/repo", "../x"))
def test_normalize_repository_rejects_unsupported_forms(source: str) -> None:
    with pytest.raises(AppManagerError, match="owner/repo"):
        normalize_repository(source)


class _FakeOpener:
    def __init__(self, outcome: object) -> None:
        self._outcome = outcome

    def open(self, request: object, timeout: float | None = None) -> object:
        if isinstance(self._outcome, BaseException):
            raise self._outcome
        return self._outcome


class _FakeResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body
        self.headers: dict[str, str] = {}

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        pass

    def read(self, size: int = -1) -> bytes:
        return self._body


class _FailingReadResponse(_FakeResponse):
    def read(self, size: int = -1) -> bytes:
        raise TimeoutError("read timed out")


def _real_transport_client(monkeypatch: pytest.MonkeyPatch, outcome: object) -> GitHubClient:
    """用假 opener 驱动真实 _request_json，覆盖网络错误映射分支。"""
    monkeypatch.setattr(github_module, "build_opener", lambda *_args, **_kwargs: _FakeOpener(outcome))
    return GitHubClient(transport=github_module._request_json)


def _rate_limit_headers() -> HTTPMessage:
    headers = HTTPMessage()
    headers["X-RateLimit-Remaining"] = "0"
    headers["X-RateLimit-Reset"] = "2000000000"
    return headers


def test_transport_reports_rate_limit_reset(monkeypatch: pytest.MonkeyPatch) -> None:
    error = HTTPError(
        "https://api.github.com/repos/a/b",
        403,
        "rate limit",
        _rate_limit_headers(),
        io.BytesIO(b""),
    )
    client = _real_transport_client(monkeypatch, error)

    with pytest.raises(AppManagerError, match=r"速率已用尽，将在 2033-05-18.*重置"):
        client.repository("owner/repo")


def test_transport_maps_plain_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    error = HTTPError("https://api.github.com/repos/a/b", 404, "not found", HTTPMessage(), io.BytesIO(b""))
    client = _real_transport_client(monkeypatch, error)

    with pytest.raises(AppManagerError, match="HTTP 404"):
        client.repository("owner/repo")


def test_transport_maps_connection_error(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _real_transport_client(monkeypatch, URLError(OSError("network down")))

    with pytest.raises(AppManagerError, match="无法连接 GitHub"):
        client.repository("owner/repo")


@pytest.mark.parametrize("body", (b'{"items":', b"[1, 2]"))
def test_transport_rejects_invalid_json_payload(monkeypatch: pytest.MonkeyPatch, body: bytes) -> None:
    client = _real_transport_client(monkeypatch, _FakeResponse(body))

    with pytest.raises(AppManagerError, match="GitHub API"):
        client.repository("owner/repo")


def test_transport_rejects_invalid_utf8_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _real_transport_client(monkeypatch, _FakeResponse(b"\xff"))

    with pytest.raises(AppManagerError, match="无效 JSON"):
        client.repository("owner/repo")


def test_transport_maps_response_read_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _real_transport_client(monkeypatch, _FailingReadResponse(b""))

    with pytest.raises(AppManagerError, match="读取 GitHub API 响应失败：TimeoutError"):
        client.repository("owner/repo")


def test_transport_rejects_oversized_response(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _real_transport_client(
        monkeypatch,
        _FakeResponse(b"x" * (github_module._MAX_RESPONSE_BYTES + 1)),
    )

    with pytest.raises(AppManagerError, match="大小上限"):
        client.repository("owner/repo")


@pytest.mark.parametrize(
    "location",
    ("http://evil.example/repos/a/b", "https://example.com/repos/a/b"),
)
def test_redirect_handler_rejects_insecure_location(location: str) -> None:
    handler = github_module._GitHubRedirectHandler()
    request = Request("https://api.github.com/repos/a/b")

    with pytest.raises(AppManagerError, match="不安全的重定向"):
        handler.redirect_request(request, io.BytesIO(), 302, "moved", HTTPMessage(), location)


def test_redirect_handler_allows_same_host_redirect() -> None:
    handler = github_module._GitHubRedirectHandler()
    request = Request("https://api.github.com/repos/a/b")

    result = handler.redirect_request(
        request,
        io.BytesIO(),
        302,
        "moved",
        HTTPMessage(),
        "https://api.github.com/repos/a/c",
    )

    assert result is None or isinstance(result, Request)

"""``aurora app search`` 的 GitHub 发现层测试：请求形状、解析、错误映射。

全部离线：假 transport 返回预置响应，唯一的网络替身是 ``httpx2.Client`` 本身。
"""

from __future__ import annotations

import base64
from typing import TYPE_CHECKING, Any

import httpx2
import pytest

from aurora.commands.app import github as github_module
from aurora.commands.app.github import (
    MAX_PAGE_SIZE,
    TOPIC_CLAUSE,
    GitHubSource,
    HttpxTransport,
)
from aurora.commands.app.manifest import MANIFEST_NAME, MAX_MANIFEST_BYTES
from aurora.commands.app.models import (
    ConfigError,
    DiscoveryError,
    GitHubRateLimitError,
    ManifestError,
    Repository,
)
from aurora.utils.project import get_running_version

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

_TOKEN = "ghp_SECRETTOKEN123"
_ENDPOINT = "https://api.github.com/search/repositories"
_LIMIT = 4 * 1024 * 1024


class FakeTransport:
    """记录调用并按序返回预置响应；预置成异常时抛出它。"""

    def __init__(self, *responses: httpx2.Response | Exception) -> None:
        self.calls: list[dict[str, Any]] = []
        self._responses = list(responses)

    def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        params: Mapping[str, str | int],
        timeout: float,
    ) -> httpx2.Response:
        self.calls.append({"url": url, "headers": headers, "params": params, "timeout": timeout})
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _repository_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "full_name": "Churk-Ben/Aurora-QQ",
        "name": "Aurora-QQ",
        "owner": {"login": "Churk-Ben"},
        "description": "QQ 通知 App",
        "stargazers_count": 12,
        "topics": ["aurorabot-app", "mcp"],
        "updated_at": "2026-09-01T12:00:00Z",
        "default_branch": "main",
        "html_url": "https://github.com/Churk-Ben/Aurora-QQ",
        "clone_url": "https://github.com/Churk-Ben/Aurora-QQ.git",
        "archived": False,
        "disabled": False,
    }
    payload.update(overrides)
    return payload


def _page(items: Sequence[object], **overrides: object) -> httpx2.Response:
    body: dict[str, object] = {"total_count": len(items), "incomplete_results": False, "items": items}
    body.update(overrides)
    return httpx2.Response(200, json=body)


def _failed(status: int, headers: Mapping[str, str] | None = None) -> httpx2.Response:
    return httpx2.Response(status, json={"message": "nope"}, headers=dict(headers or {}))


def _source(*responses: httpx2.Response | Exception, token: str | None = None) -> tuple[GitHubSource, FakeTransport]:
    transport = FakeTransport(*responses)
    return GitHubSource(transport, token=token), transport


def test_an_empty_query_still_carries_the_topic_to_the_api() -> None:
    source, transport = _source(_page([]))

    source.search()

    assert transport.calls[0]["params"]["q"] == TOPIC_CLAUSE


# --- 请求形状 -----------------------------------------------------------------


def test_arguments_are_checked_before_any_request() -> None:
    source, transport = _source(_page([]))

    with pytest.raises(ConfigError):
        source.search(page=0)

    assert transport.calls == []


def test_the_search_endpoint_is_used() -> None:
    source, transport = _source(_page([]))

    source.search()

    assert transport.calls[0]["url"] == _ENDPOINT


def test_paging_becomes_query_parameters() -> None:
    source, transport = _source(_page([]))

    source.search("clock", page=3, page_size=5)

    assert transport.calls[0]["params"] == {"q": f"{TOPIC_CLAUSE} clock", "page": 3, "per_page": 5}


def test_no_sort_parameters_are_sent_by_default() -> None:
    """默认交给 GitHub 的 best match 排序，不替用户决定按 stars 排。"""
    source, transport = _source(_page([]))

    source.search()

    assert "sort" not in transport.calls[0]["params"]
    assert "order" not in transport.calls[0]["params"]


def test_sort_defaults_the_order_to_descending() -> None:
    source, transport = _source(_page([]))

    source.search(sort="updated")

    params = transport.calls[0]["params"]
    assert (params["sort"], params["order"]) == ("updated", "desc")


def test_an_explicit_order_is_forwarded() -> None:
    source, transport = _source(_page([]))

    source.search(sort="stars", order="asc")

    params = transport.calls[0]["params"]
    assert (params["sort"], params["order"]) == ("stars", "asc")


def test_the_user_agent_carries_the_running_version() -> None:
    source, transport = _source(_page([]))

    source.search()

    headers = transport.calls[0]["headers"]
    assert headers["User-Agent"] == f"AuroraBot/{get_running_version()}"
    assert headers["Accept"] == "application/vnd.github+json"
    assert headers["X-GitHub-Api-Version"] == "2022-11-28"


def test_no_authorization_header_without_a_token() -> None:
    source, transport = _source(_page([]))

    source.search()

    assert "Authorization" not in transport.calls[0]["headers"]


@pytest.mark.parametrize("token", [_TOKEN, f"  {_TOKEN}  "])
def test_a_token_becomes_a_bearer_header(token: str) -> None:
    source, transport = _source(_page([]), token=token)

    source.search()

    assert transport.calls[0]["headers"]["Authorization"] == f"Bearer {_TOKEN}"


@pytest.mark.parametrize("token", ["", "   ", "\t"])
def test_a_blank_token_is_no_token(token: str) -> None:
    source, transport = _source(_page([]), token=token)

    source.search()

    assert "Authorization" not in transport.calls[0]["headers"]


def test_the_token_only_ever_travels_in_the_authorization_header() -> None:
    """URL 与查询串会进访问日志、代理日志和异常文本；token 只能放在头里。"""
    source, transport = _source(_page([]), token=_TOKEN)

    source.search("clock")

    call = transport.calls[0]
    assert _TOKEN not in call["url"]
    assert _TOKEN not in str(call["params"])
    assert call["headers"]["Authorization"] == f"Bearer {_TOKEN}"


# --- 响应解析 -----------------------------------------------------------------


def test_a_full_page_maps_every_field() -> None:
    source, _ = _source(_page([_repository_payload()]))

    result = source.search("qq")

    assert (result.page, result.page_size, result.total_count, result.incomplete_results) == (1, 20, 1, False)
    assert result.items == (
        Repository(
            full_name="Churk-Ben/Aurora-QQ",
            owner="Churk-Ben",
            name="Aurora-QQ",
            description="QQ 通知 App",
            stars=12,
            topics=("aurorabot-app", "mcp"),
            updated_at="2026-09-01T12:00:00Z",
            default_branch="main",
            html_url="https://github.com/Churk-Ben/Aurora-QQ",
            clone_url="https://github.com/Churk-Ben/Aurora-QQ.git",
            archived=False,
            disabled=False,
        ),
    )


def test_the_reported_page_reflects_the_request_not_the_response() -> None:
    """GitHub 不回显分页参数，页码只能以请求为准。"""
    source, _ = _source(_page([_repository_payload()]))

    result = source.search(page=4, page_size=7)

    assert (result.page, result.page_size) == (4, 7)


def test_an_empty_result_is_not_an_error() -> None:
    source, _ = _source(_page([]))

    assert source.search().items == ()


def test_incomplete_results_are_carried_through() -> None:
    source, _ = _source(_page([_repository_payload()], incomplete_results=True))

    assert source.search().incomplete_results is True


def test_a_missing_total_count_falls_back_to_zero() -> None:
    source, _ = _source(_page([], total_count=None))

    assert source.search().total_count == 0


@pytest.mark.parametrize("key", ["description", "updated_at", "default_branch"])
def test_missing_optional_text_becomes_the_default(key: str) -> None:
    payload = _repository_payload()
    del payload[key]
    source, _ = _source(_page([payload]))

    repository = source.search().items[0]

    expected = None if key == "description" else ""
    assert getattr(repository, key) == expected


def test_a_null_description_becomes_none() -> None:
    source, _ = _source(_page([_repository_payload(description=None)]))

    assert source.search().items[0].description is None


def test_missing_stars_and_topics_fall_back_to_defaults() -> None:
    payload = _repository_payload()
    del payload["stargazers_count"]
    del payload["topics"]
    source, _ = _source(_page([payload]))

    repository = source.search().items[0]

    assert (repository.stars, repository.topics) == (0, ())


def test_a_boolean_is_not_accepted_as_a_star_count() -> None:
    """``True`` 在 Python 里是 int；照收会让表格显示 stars 1。"""
    source, _ = _source(_page([_repository_payload(stargazers_count=True)]))

    assert source.search().items[0].stars == 0


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({}, "active"),
        ({"archived": True}, "archived"),
        ({"disabled": True}, "disabled"),
        ({"archived": True, "disabled": True}, "disabled"),
    ],
)
def test_status_prefers_disabled_over_archived(overrides: dict[str, object], expected: str) -> None:
    source, _ = _source(_page([_repository_payload(**overrides)]))

    assert source.search().items[0].status == expected


@pytest.mark.parametrize("key", ["full_name", "name", "html_url", "clone_url"])
def test_a_missing_decisive_field_fails_the_whole_page(key: str) -> None:
    """半残条目比失败更糟：后续 install 会照着它生成一个错的 package。"""
    payload = _repository_payload()
    del payload[key]
    source, _ = _source(_page([payload]))

    with pytest.raises(DiscoveryError, match=key):
        source.search()


@pytest.mark.parametrize("owner", [{}, {"login": ""}, {"login": 7}, "Churk-Ben", None])
def test_a_broken_owner_object_fails_the_page(owner: object) -> None:
    source, _ = _source(_page([_repository_payload(owner=owner)]))

    with pytest.raises(DiscoveryError, match=r"owner\.login"):
        source.search()


@pytest.mark.parametrize("items", [None, {}, "abc", 7])
def test_a_non_array_items_field_fails_the_page(items: object) -> None:
    body = {"total_count": 0, "incomplete_results": False, "items": items}
    source, _ = _source(httpx2.Response(200, json=body))

    with pytest.raises(DiscoveryError, match="items"):
        source.search()


@pytest.mark.parametrize("item", ["abc", 7, None, ["nested"]])
def test_a_non_object_item_fails_the_page(item: object) -> None:
    source, _ = _source(_page([item]))

    with pytest.raises(DiscoveryError):
        source.search()


def test_a_non_json_body_is_a_discovery_error() -> None:
    source, _ = _source(httpx2.Response(200, content=b"<html>rate limited</html>"))

    with pytest.raises(DiscoveryError, match="JSON"):
        source.search()


@pytest.mark.parametrize("body", ['["a"]', '"text"', "7", "null"])
def test_json_that_is_not_an_object_is_a_discovery_error(body: str) -> None:
    source, _ = _source(httpx2.Response(200, content=body.encode()))

    with pytest.raises(DiscoveryError):
        source.search()


def test_the_size_limit_is_the_documented_four_megabytes() -> None:
    assert github_module._MAX_RESPONSE_BYTES == _LIMIT


def test_an_oversized_body_is_rejected_before_parsing() -> None:
    source, _ = _source(httpx2.Response(200, content=b"x" * (_LIMIT + 1)))

    with pytest.raises(DiscoveryError, match="大小上限"):
        source.search()


def test_an_oversized_content_length_is_rejected_without_reading_the_body() -> None:
    """Content-Length 是廉价的先手；头与实际不符时再看字节数。"""
    response = httpx2.Response(200, content=b"{}", headers={"Content-Length": str(_LIMIT + 1)})
    source, _ = _source(response)

    with pytest.raises(DiscoveryError, match="大小上限"):
        source.search()


def test_an_unparsable_content_length_does_not_block_the_body_check() -> None:
    response = httpx2.Response(200, json={"items": []}, headers={"Content-Length": "chunked"})
    source, _ = _source(response)

    assert source.search().items == ()


def test_a_realistic_page_stays_under_the_size_limit() -> None:
    """上限必须留足余量：100 条满字段结果远不该撞到它。"""
    items = [_repository_payload(description="描述" * 40) for _ in range(MAX_PAGE_SIZE)]
    source, _ = _source(_page(items, total_count=len(items)))

    assert len(source.search(page_size=MAX_PAGE_SIZE).items) == MAX_PAGE_SIZE


# --- 状态映射 -----------------------------------------------------------------


@pytest.mark.parametrize("status", [201, 204, 302])
def test_anything_but_200_is_a_discovery_error(status: int) -> None:
    """只有 200 算成功：Search 不返回 201/204，而 302 说明请求被引向了别处。"""
    source, _ = _source(_failed(status))

    with pytest.raises(DiscoveryError, match=str(status)):
        source.search()


def test_a_401_points_at_the_token() -> None:
    source, _ = _source(_failed(401))

    with pytest.raises(DiscoveryError, match="GITHUB_TOKEN"):
        source.search()


def test_a_404_is_reported_as_such() -> None:
    source, _ = _source(_failed(404))

    with pytest.raises(DiscoveryError, match="404"):
        source.search()


def test_a_server_error_does_not_claim_the_user_did_something_wrong() -> None:
    source, _ = _source(_failed(500))

    with pytest.raises(DiscoveryError, match="暂时不可用"):
        source.search()


def test_a_403_with_no_quota_left_is_a_rate_limit_error() -> None:
    source, _ = _source(_failed(403, {"X-RateLimit-Remaining": "0"}))

    with pytest.raises(GitHubRateLimitError):
        source.search()


def test_a_429_is_a_rate_limit_error_even_without_headers() -> None:
    source, _ = _source(_failed(429))

    with pytest.raises(GitHubRateLimitError):
        source.search()


def test_a_403_with_quota_left_is_not_a_rate_limit_error() -> None:
    """配额还在的 403 是别的原因；报成「配额耗尽」会把用户引向错误的解法。"""
    source, _ = _source(_failed(403, {"X-RateLimit-Remaining": "42"}))

    with pytest.raises(DiscoveryError, match="HTTP 403") as error_info:
        source.search()

    assert not isinstance(error_info.value, GitHubRateLimitError)


def test_an_unparsable_remaining_header_is_not_treated_as_exhausted() -> None:
    source, _ = _source(_failed(403, {"X-RateLimit-Remaining": "lots"}))

    with pytest.raises(DiscoveryError) as error_info:
        source.search()

    assert not isinstance(error_info.value, GitHubRateLimitError)


def test_the_rate_limit_message_carries_the_reset_time() -> None:
    source, _ = _source(_failed(403, {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1790000000"}))

    with pytest.raises(GitHubRateLimitError, match=r"将于 .+ 重置"):
        source.search()


def test_an_unusable_reset_header_is_simply_omitted() -> None:
    source, _ = _source(_failed(403, {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "not-a-time"}))

    with pytest.raises(GitHubRateLimitError) as error_info:
        source.search()

    assert "将于" not in str(error_info.value)


def test_the_retry_after_header_is_reported_in_seconds() -> None:
    source, _ = _source(_failed(429, {"Retry-After": "60"}))

    with pytest.raises(GitHubRateLimitError, match="60 秒"):
        source.search()


def test_the_rate_limit_message_names_the_way_out() -> None:
    source, _ = _source(_failed(429))

    with pytest.raises(GitHubRateLimitError, match="GITHUB_TOKEN"):
        source.search()


# --- 传输层异常与凭据 -----------------------------------------------------------------


@pytest.mark.parametrize(
    "error",
    [httpx2.ConnectError("boom"), httpx2.TimeoutException("boom"), httpx2.TooManyRedirects("boom")],
)
def test_a_transport_failure_becomes_a_discovery_error(error: httpx2.HTTPError) -> None:
    source, _ = _source(error)

    with pytest.raises(DiscoveryError, match=type(error).__name__):
        source.search()


def test_a_transport_failure_does_not_leak_the_request_context() -> None:
    """httpx2 的异常文本可能带上 URL 与请求头，而请求头里有 token。"""
    source, _ = _source(httpx2.ConnectError(f"failed for {_ENDPOINT} with Bearer {_TOKEN}"), token=_TOKEN)

    with pytest.raises(DiscoveryError) as error_info:
        source.search()

    assert _TOKEN not in str(error_info.value)
    assert "Bearer" not in str(error_info.value)


@pytest.mark.parametrize("status", [401, 403, 404, 429, 500])
def test_no_error_message_ever_contains_the_token(status: int) -> None:
    """错误信息会原样打印给用户，也可能被贴进 issue。"""
    source, _ = _source(_failed(status, {"X-RateLimit-Remaining": "0"}), token=_TOKEN)

    with pytest.raises(DiscoveryError) as error_info:
        source.search()

    assert _TOKEN not in str(error_info.value)


# --- 默认 transport ----------------------------------------------------------------


class _FakeClient:
    """替掉 httpx2.Client；只记录构造、get 与退出，不发任何请求。"""

    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs
        self.gets: list[dict[str, Any]] = []
        self.closed = False

    def __enter__(self) -> _FakeClient:
        return self

    def __exit__(self, *_: object) -> bool:
        self.closed = True
        return False

    def get(self, url: str, **kwargs: object) -> httpx2.Response:
        self.gets.append({"url": url, **kwargs})
        return _page([])


@pytest.fixture
def fake_client(monkeypatch: pytest.MonkeyPatch) -> list[_FakeClient]:
    """装上假 Client 并返回创建记录；测试从这里读出真实传参。"""
    created: list[_FakeClient] = []

    def build(**kwargs: object) -> _FakeClient:
        created.append(_FakeClient(**kwargs))
        return created[-1]

    monkeypatch.setattr(httpx2, "Client", build)
    return created


def test_the_default_transport_does_not_follow_redirects(fake_client: list[_FakeClient]) -> None:
    source = GitHubSource(HttpxTransport())

    source.search()

    assert fake_client[0].kwargs["follow_redirects"] is False
    assert fake_client[0].gets[0]["url"] == _ENDPOINT


def test_the_default_transport_forwards_headers_and_params(fake_client: list[_FakeClient]) -> None:
    """协议两端要真的接得上：假 transport 验证了语义，这里验证接线。"""
    source = GitHubSource(HttpxTransport(), token=_TOKEN)

    source.search("clock", page=2)

    call = fake_client[0].gets[0]
    assert call["headers"]["Authorization"] == f"Bearer {_TOKEN}"
    assert call["params"] == {"q": f"{TOPIC_CLAUSE} clock", "page": 2, "per_page": 20}


def test_the_default_transport_closes_its_client(fake_client: list[_FakeClient]) -> None:
    """每次调用开一个短命 Client 是有意的：搜索是低频命令，不需要连接池。"""
    source = GitHubSource(HttpxTransport())

    source.search()

    assert fake_client[0].closed is True


# --- 清单（Contents API） ------------------------------------------------------


def _contents(content: str, **overrides: object) -> httpx2.Response:
    """一份 Contents API 的文件响应体。"""
    body: dict[str, object] = {
        "type": "file",
        "encoding": "base64",
        "content": base64.b64encode(content.encode("utf-8")).decode(),
    }
    body.update(overrides)
    return httpx2.Response(200, json=body)


def _raw_contents(payload: bytes, **overrides: object) -> httpx2.Response:
    """直接给一份字节，用来测编码与体积：它们都是解码之后才看得见的。"""
    body: dict[str, object] = {"type": "file", "encoding": "base64", "content": base64.b64encode(payload).decode()}
    body.update(overrides)
    return httpx2.Response(200, json=body)


def test_the_manifest_is_read_from_the_repository_root() -> None:
    source, transport = _source(_contents('manifest_version = 1\n[server]\ncommand = ["uv"]\n'))

    content = source.manifest("Churk-Ben/Aurora-QQ")

    assert content == 'manifest_version = 1\n[server]\ncommand = ["uv"]\n'
    assert transport.calls[0]["url"] == f"https://api.github.com/repos/Churk-Ben/Aurora-QQ/contents/{MANIFEST_NAME}"


def test_no_ref_means_the_default_branch() -> None:
    source, transport = _source(_contents("manifest_version = 1\n"))

    source.manifest("Churk-Ben/Aurora-QQ")

    assert transport.calls[0]["params"] == {}


def test_a_ref_is_read_from_that_ref() -> None:
    """从 main 读到清单却去装一个 tag，等于按另一个版本的声明安装。"""
    source, transport = _source(_contents("manifest_version = 1\n"))

    source.manifest("Churk-Ben/Aurora-QQ", ref="v1.2.0")

    assert transport.calls[0]["params"] == {"ref": "v1.2.0"}


def test_a_missing_manifest_is_not_an_error() -> None:
    """仓库元数据刚刚取到了，所以这里的 404 只能是「没有这个文件」。"""
    source, _ = _source(_failed(404))

    assert source.manifest("Churk-Ben/Aurora-QQ") is None


def test_a_directory_instead_of_a_file_is_unusable() -> None:
    source, _ = _source(_contents("", type="dir"))

    with pytest.raises(ManifestError, match="不是仓库根目录下的一个文件"):
        source.manifest("Churk-Ben/Aurora-QQ")


@pytest.mark.parametrize(
    "payload",
    [
        {"type": "file", "encoding": "none", "content": ""},
        {"type": "file", "encoding": "base64"},
        {"type": "file", "encoding": "base64", "content": ""},
    ],
)
def test_an_unavailable_content_field_is_unusable(payload: dict[str, object]) -> None:
    """超过 1 MB 的文件 GitHub 会返回空 content 与 ``encoding: none``。"""
    source, _ = _source(httpx2.Response(200, json=payload))

    with pytest.raises(ManifestError, match="解码"):
        source.manifest("Churk-Ben/Aurora-QQ")


def test_undecodable_base64_is_unusable() -> None:
    """GitHub 说是 base64 但内容解不开：宁可报不可用，也不拿半份字节去解析 TOML。"""
    body = {"type": "file", "encoding": "base64", "content": "a"}
    source, _ = _source(httpx2.Response(200, json=body))

    with pytest.raises(ManifestError, match="base64"):
        source.manifest("Churk-Ben/Aurora-QQ")


def test_an_oversized_manifest_is_unusable() -> None:
    source, _ = _source(_raw_contents(b"x" * (MAX_MANIFEST_BYTES + 1)))

    with pytest.raises(ManifestError, match="字节"):
        source.manifest("Churk-Ben/Aurora-QQ")


def test_a_manifest_with_a_size_boundary_is_accepted() -> None:
    """边界值属于可用范围：正好等于上限的一份仍然要能读出来。"""
    source, _ = _source(_raw_contents(b"x" * MAX_MANIFEST_BYTES))

    assert len(source.manifest("Churk-Ben/Aurora-QQ") or "") == MAX_MANIFEST_BYTES


def test_a_non_utf8_manifest_is_unusable() -> None:
    source, _ = _source(_raw_contents(b"\xff\xfe\x00"))

    with pytest.raises(ManifestError, match="UTF-8"):
        source.manifest("Churk-Ben/Aurora-QQ")


def test_the_error_names_the_source_it_read_from() -> None:
    """同一个仓库的两个 ref 各有各的清单，出错时必须说清是哪一份。"""
    source, _ = _source(_contents("", type="symlink"))

    with pytest.raises(ManifestError) as error_info:
        source.manifest("Churk-Ben/Aurora-QQ", ref="v2")

    assert "Churk-Ben/Aurora-QQ@v2" in str(error_info.value)


def test_a_rate_limited_manifest_read_says_so() -> None:
    source, _ = _source(_failed(403, {"X-RateLimit-Remaining": "0"}))

    with pytest.raises(GitHubRateLimitError):
        source.manifest("Churk-Ben/Aurora-QQ")


def test_a_401_on_the_manifest_read_points_at_the_token() -> None:
    source, _ = _source(_failed(401))

    with pytest.raises(DiscoveryError, match="GITHUB_TOKEN"):
        source.manifest("Churk-Ben/Aurora-QQ")


def test_the_manifest_token_only_travels_in_the_authorization_header() -> None:
    source, transport = _source(_contents("manifest_version = 1\n"), token=_TOKEN)

    source.manifest("Churk-Ben/Aurora-QQ", ref="main")

    call = transport.calls[0]
    assert _TOKEN not in call["url"]
    assert _TOKEN not in str(call["params"])
    assert call["headers"]["Authorization"] == f"Bearer {_TOKEN}"

"""GitHub Repository Search 与仓库元数据的最小客户端。"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from http.client import HTTPException
from typing import TYPE_CHECKING, Any, cast
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from aurora.apps.models import AppManagerError, Repository, RepositoryPage, normalize_repository

if TYPE_CHECKING:
    from http.client import HTTPMessage
    from typing import IO

_API_ROOT = "https://api.github.com"
_API_HOST = "api.github.com"
_TOPIC = "aurorabot-app"
_MAX_RESPONSE_BYTES = 4 * 1024 * 1024
_SEARCH_LIMIT = 1000
_MAX_PAGE_SIZE = 100
_SORTS = frozenset({"stars", "updated"})
_ORDERS = frozenset({"asc", "desc"})


@dataclass(frozen=True, slots=True)
class JsonResponse:
    """可由离线 fake 构造的 GitHub JSON 响应。"""

    payload: Mapping[str, Any]
    headers: Mapping[str, str]


type JsonTransport = Callable[[str, Mapping[str, str]], JsonResponse]


class GitHubClient:
    """只访问 api.github.com 的同步 JSON 客户端。"""

    def __init__(self, *, token: str | None = None, transport: JsonTransport | None = None) -> None:
        self._token = token
        self._transport = transport or _request_json

    def search(
        self,
        *,
        query: str = "",
        page: int = 1,
        page_size: int = 20,
        sort: str = "stars",
        order: str = "desc",
    ) -> RepositoryPage:
        _validate_search(page, page_size, sort, order)
        terms = [f"topic:{_TOPIC}"]
        if query.strip():
            terms.append(query.strip())
        parameters = urlencode(
            {
                "q": " ".join(terms),
                "page": page,
                "per_page": page_size,
                "sort": sort,
                "order": order,
            }
        )
        response = self._get(f"/search/repositories?{parameters}")
        items = response.payload.get("items")
        if not isinstance(items, list):
            raise AppManagerError("GitHub 搜索响应缺少 items")
        return RepositoryPage(
            _non_negative_integer(response.payload, "total_count"),
            page,
            page_size,
            _boolean(response.payload, "incomplete_results"),
            tuple(_repository(item) for item in items),
        )

    def repository(self, source: str) -> Repository:
        identifier = normalize_repository(source)
        response = self._get(f"/repos/{quote(identifier, safe='/')}")
        return _repository(response.payload)

    def _get(self, path: str) -> JsonResponse:
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "AuroraBot-app-manager",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return self._transport(f"{_API_ROOT}{path}", headers)


class _GitHubRedirectHandler(HTTPRedirectHandler):
    def redirect_request(
        self,
        req: Request,
        fp: IO[bytes],
        code: int,
        msg: str,
        headers: HTTPMessage,
        newurl: str,
    ) -> Request | None:
        parsed = urlsplit(newurl)
        if parsed.scheme != "https" or parsed.hostname != _API_HOST:
            raise AppManagerError("GitHub API 返回了不安全的重定向")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _request_json(url: str, headers: Mapping[str, str]) -> JsonResponse:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname != _API_HOST:
        raise AppManagerError("GitHub API URL 不受支持")
    request = Request(url, headers=dict(headers))
    opener = build_opener(_GitHubRedirectHandler())
    try:
        with opener.open(request, timeout=30) as response:
            body = response.read(_MAX_RESPONSE_BYTES + 1)
            if len(body) > _MAX_RESPONSE_BYTES:
                raise AppManagerError("GitHub API 响应超过大小上限")
            payload = json.loads(body)
            response_headers = {key.lower(): value for key, value in response.headers.items()}
    except HTTPError as error:
        raise _http_error(error) from error
    except URLError as error:
        raise AppManagerError(f"无法连接 GitHub：{error.reason}") from error
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise AppManagerError("GitHub API 返回了无效 JSON") from error
    except (HTTPException, OSError) as error:
        raise AppManagerError(f"读取 GitHub API 响应失败：{type(error).__name__}") from error
    if not isinstance(payload, Mapping):
        raise AppManagerError("GitHub API 返回的 JSON 不是对象")
    return JsonResponse(cast("Mapping[str, Any]", payload), response_headers)


def _http_error(error: HTTPError) -> AppManagerError:
    remaining = error.headers.get("X-RateLimit-Remaining")
    reset = error.headers.get("X-RateLimit-Reset")
    if error.code in {403, 429} and remaining == "0" and reset is not None:
        try:
            reset_at = datetime.fromtimestamp(int(reset), tz=UTC).isoformat()
        except ValueError:
            reset_at = "未知时间"
        return AppManagerError(f"GitHub API 速率已用尽，将在 {reset_at} 重置")
    return AppManagerError(f"GitHub API 请求失败：HTTP {error.code}")


def _validate_search(page: int, page_size: int, sort: str, order: str) -> None:
    if page < 1:
        raise AppManagerError("page 必须大于等于 1")
    if page_size < 1 or page_size > _MAX_PAGE_SIZE:
        raise AppManagerError("page-size 必须在 1 到 100 之间")
    if (page - 1) * page_size >= _SEARCH_LIMIT:
        raise AppManagerError("GitHub Search 只能访问前 1000 条结果")
    if sort not in _SORTS:
        raise AppManagerError("sort 必须是 stars 或 updated")
    if order not in _ORDERS:
        raise AppManagerError("order 必须是 asc 或 desc")


def _repository(value: object) -> Repository:
    if not isinstance(value, Mapping):
        raise AppManagerError("GitHub 仓库响应格式无效")
    topics = value.get("topics", [])
    if not isinstance(topics, list) or any(not isinstance(item, str) for item in topics):
        raise AppManagerError("GitHub 仓库 topics 格式无效")
    description = value.get("description")
    return Repository(
        normalize_repository(_text(value, "full_name")),
        description if isinstance(description, str) else "",
        _non_negative_integer(value, "stargazers_count"),
        _text(value, "default_branch"),
        _text(value, "html_url"),
        _text(value, "clone_url"),
        tuple(topics),
        _boolean(value, "archived"),
        _boolean(value, "disabled"),
        _text(value, "updated_at"),
    )


def _text(value: Mapping[str, object], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item.strip():
        raise AppManagerError(f"GitHub 字段 {key} 必须是非空文本")
    return item.strip()


def _non_negative_integer(value: Mapping[str, object], key: str) -> int:
    item = value.get(key)
    if not isinstance(item, int) or isinstance(item, bool) or item < 0:
        raise AppManagerError(f"GitHub 字段 {key} 必须是非负整数")
    return item


def _boolean(value: Mapping[str, object], key: str) -> bool:
    item = value.get(key)
    if not isinstance(item, bool):
        raise AppManagerError(f"GitHub 字段 {key} 必须是布尔值")
    return item


__all__ = ["GitHubClient", "JsonResponse", "JsonTransport"]

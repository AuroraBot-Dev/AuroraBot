"""通过 GitHub API 搜索仓库并读取元数据与安装清单。"""

from __future__ import annotations

import base64
import binascii
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Protocol
from urllib.parse import quote

import httpx2

from aurora.commands.app.manifest import MANIFEST_NAME, MAX_MANIFEST_BYTES, manifest_source, unusable_manifest
from aurora.commands.app.models import (
    ConfigError,
    DiscoveryError,
    GitHubRateLimitError,
    Repository,
    RepositoryPage,
)
from aurora.utils.project import get_running_version

TOPIC = "aurorabot-app"
TOPIC_CLAUSE = f"topic:{TOPIC}"
SORT_FIELDS = ("stars", "forks", "updated")
ORDER_FIELDS = ("asc", "desc")
DEFAULT_PAGE = 1
DEFAULT_PAGE_SIZE = 20
DEFAULT_ORDER = "desc"
MAX_PAGE_SIZE = 100
MAX_RESULTS = 1000

_SEARCH_ENDPOINT = "https://api.github.com/search/repositories"
_REPOSITORIES_ENDPOINT = "https://api.github.com/repos"
_API_VERSION = "2022-11-28"
_ACCEPT = "application/vnd.github+json"
_TIMEOUT_SECONDS = 30.0
_MAX_RESPONSE_BYTES = 4 * 1024 * 1024
_RESET_FORMAT = "%Y-%m-%d %H:%M:%S"
_RATE_LIMIT_REMAINING = "x-ratelimit-remaining"
_RATE_LIMIT_RESET = "x-ratelimit-reset"


class HttpTransport(Protocol):
    """``GitHubSource`` 依赖的最小 HTTP 边界；测试用假实现替换它。"""

    def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        params: Mapping[str, str | int],
        timeout: float,
    ) -> httpx2.Response: ...


class HttpxTransport:
    """默认 transport：用项目已声明的 httpx2 发同步请求。

    不跟随重定向，与 ``src/mcp/client.py`` 的取舍一致：GitHub API 正常不重定向，
    一旦重定向就说明请求被引向了别处，应当作为失败处理而不是跟过去。
    """

    def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        params: Mapping[str, str | int],
        timeout: float,
    ) -> httpx2.Response:
        with httpx2.Client(follow_redirects=False, timeout=httpx2.Timeout(timeout)) as client:
            return client.get(url, headers=dict(headers), params=dict(params))


class GitHubSource:
    """GitHub 仓库搜索；只做发现，不做任何本地判断。"""

    def __init__(self, transport: HttpTransport, token: str | None = None) -> None:
        self._transport = transport
        self._token = token.strip() if token and token.strip() else None

    def search(
        self,
        query: str | None = None,
        *,
        page: int = DEFAULT_PAGE,
        page_size: int = DEFAULT_PAGE_SIZE,
        sort: str | None = None,
        order: str | None = None,
    ) -> RepositoryPage:
        """搜索带 ``aurorabot-app`` topic 的仓库；参数越界在发请求前就拒绝。"""
        check_search_arguments(page=page, page_size=page_size, sort=sort, order=order)
        response = self._get(_SEARCH_ENDPOINT, _search_parameters(query, page, page_size, sort, order))
        _raise_for_status(response)
        payload = _payload(response)
        return RepositoryPage(
            items=_items(payload),
            page=page,
            page_size=page_size,
            total_count=_non_negative(payload, "total_count"),
            incomplete_results=_flag(payload, "incomplete_results"),
        )

    def repository(self, full_name: str) -> Repository:
        """从 GitHub API 读取仓库名称、默认分支与克隆地址。"""
        response = self._get(_repository_endpoint(full_name), {})
        _raise_for_status(response, resource="仓库")
        return _repository(_payload(response))

    def manifest(self, full_name: str, *, ref: str | None = None) -> str | None:
        """克隆前读取仓库根目录的安装清单；Contents API 返回 404 时返回 None。"""
        response = self._get(_contents_endpoint(full_name, MANIFEST_NAME), _ref_parameters(ref))
        if response.status_code == httpx2.codes.NOT_FOUND:
            return None
        _raise_for_status(response, resource="清单")
        return _manifest_content(_payload(response), manifest_source(full_name, ref))

    def _get(self, url: str, parameters: Mapping[str, str | int]) -> httpx2.Response:
        """发送元数据请求，公开错误只包含类型名，避免带出含认证信息的请求上下文。"""
        try:
            return self._transport.get(
                url,
                headers=_headers(self._token),
                params=parameters,
                timeout=_TIMEOUT_SECONDS,
            )
        except httpx2.HTTPError as error:
            raise DiscoveryError(f"无法访问 GitHub（{type(error).__name__}）") from error


def build_search_query(query: str | None) -> str:
    """把用户输入并到固定的 topic 子句之后。

    只有空白时只留 topic。不解析 GitHub 高级搜索语法：``language:python`` 这类
    子句原样传给 GitHub，由它决定含义。
    """
    normalized = (query or "").strip()
    return f"{TOPIC_CLAUSE} {normalized}" if normalized else TOPIC_CLAUSE


def check_search_arguments(*, page: int, page_size: int, sort: str | None, order: str | None) -> None:
    """验证搜索参数，拒绝超过前 1000 条结果的分页；参数错误使用退出码 2。"""
    if page < 1:
        raise ConfigError("--page 必须大于等于 1")
    if not 1 <= page_size <= MAX_PAGE_SIZE:
        raise ConfigError(f"--page-size 必须在 1 到 {MAX_PAGE_SIZE} 之间")
    if sort is not None and sort not in SORT_FIELDS:
        raise ConfigError(f"--sort 必须是 {'、'.join(SORT_FIELDS)} 之一")
    if order is not None and order not in ORDER_FIELDS:
        raise ConfigError(f"--order 必须是 {'、'.join(ORDER_FIELDS)} 之一")
    if order is not None and sort is None:
        raise ConfigError("--order 需要与 --sort 一起使用")
    if (page - 1) * page_size >= MAX_RESULTS:
        raise ConfigError(
            f"--page 超出范围：GitHub Search 只暴露前 {MAX_RESULTS} 条结果，"
            f"每页 {page_size} 条时最多到第 {MAX_RESULTS // page_size} 页"
        )


def _search_parameters(
    query: str | None, page: int, page_size: int, sort: str | None, order: str | None
) -> dict[str, str | int]:
    """构造查询参数；编码交给 transport 的 params，不手工拼 URL。

    不传 ``--sort`` 时不带 sort/order，让 GitHub 用 best match —— 这比替用户
    决定按 stars 排序更符合搜索语义。
    """
    parameters: dict[str, str | int] = {
        "q": build_search_query(query),
        "page": page,
        "per_page": page_size,
    }
    if sort is not None:
        parameters["sort"] = sort
        parameters["order"] = order or DEFAULT_ORDER
    return parameters


def _repository_base(full_name: str) -> str:
    """``/repos/{owner}/{repo}``；两段各自 percent-encoding，不手工拼裸路径。

    这里只保证 URL 拼得出来。仓库名的完整规则在 ``install.check_requested_name``，
    调用方已经先过了一遍；这一条是兜底，免得调用方漏掉时拼出一个指向别处的 URL。
    """
    owner, separator, name = full_name.partition("/")
    if not separator or not owner or not name:
        raise DiscoveryError(f"仓库全名必须是 owner/repo 两段：{full_name}")
    encoded = "/".join(quote(part, safe="") for part in (owner, name))
    return f"{_REPOSITORIES_ENDPOINT}/{encoded}"


def _repository_endpoint(full_name: str) -> str:
    return _repository_base(full_name)


def _contents_endpoint(full_name: str, path: str) -> str:
    """``/repos/{owner}/{repo}/contents/{path}``；文件名同样要转义。"""
    return f"{_repository_base(full_name)}/contents/{quote(path, safe='')}"


def _ref_parameters(ref: str | None) -> dict[str, str]:
    """指定 --ref 时从那个 ref 读清单；不指定就由 GitHub 用默认分支。

    清单必须与将要克隆的 ref 一致：从 main 读到清单、却去装一个 tag，等于按另一
    个版本的声明安装。
    """
    return {} if ref is None else {"ref": ref}


def _manifest_content(payload: Mapping[str, object], source: str) -> str:
    """把 Contents API 的文件响应解成文本。

    ``content`` 是 base64（Contents API 对 1 MB 以上的文件会返回空 content 与
    ``encoding: none``），所以「拿不到内容」是必须处理的正常分支，不是异常。
    """
    if payload.get("type") != "file":
        raise unusable_manifest(source, "它不是仓库根目录下的一个文件")
    content = payload.get("content")
    if payload.get("encoding") != "base64" or not isinstance(content, str) or not content:
        raise unusable_manifest(source, "GitHub 没有返回可解码的内容，文件可能超过 1 MB")
    try:
        raw = base64.b64decode(content, validate=False)
    except (binascii.Error, ValueError) as error:
        raise unusable_manifest(source, f"内容不是合法 base64（{type(error).__name__}）") from error
    if len(raw) > MAX_MANIFEST_BYTES:
        raise unusable_manifest(source, f"超过 {MAX_MANIFEST_BYTES} 字节，不像一份声明文件")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise unusable_manifest(source, "内容不是 UTF-8 文本") from error


def _headers(token: str | None) -> dict[str, str]:
    """GitHub 请求头；token 只在这里出现，绝不进入错误信息或日志。"""
    headers = {
        "Accept": _ACCEPT,
        "User-Agent": f"AuroraBot/{get_running_version()}",
        "X-GitHub-Api-Version": _API_VERSION,
    }
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _raise_for_status(response: httpx2.Response, *, resource: str = "搜索") -> None:
    """将 GitHub HTTP 状态转换为搜索、认证或配额错误。"""
    status = response.status_code
    if status == httpx2.codes.OK:
        return
    if status == httpx2.codes.UNAUTHORIZED:
        raise DiscoveryError("GitHub 认证失败，请检查 GITHUB_TOKEN")
    if status in {httpx2.codes.FORBIDDEN, httpx2.codes.TOO_MANY_REQUESTS}:
        if status == httpx2.codes.TOO_MANY_REQUESTS or _remaining(response) == 0:
            raise GitHubRateLimitError(_rate_limit_message(response))
        raise DiscoveryError(f"GitHub 拒绝了这次请求（HTTP {status}）")
    if status == httpx2.codes.NOT_FOUND:
        raise DiscoveryError(f"GitHub {resource}接口返回 HTTP 404")
    if status >= httpx2.codes.INTERNAL_SERVER_ERROR:
        raise DiscoveryError("GitHub 服务暂时不可用")
    raise DiscoveryError(f"GitHub 请求失败（HTTP {status}）")


def _remaining(response: httpx2.Response) -> int | None:
    """读取剩余配额；读不到就返回 None，让调用方退回普通错误。"""
    raw = response.headers.get(_RATE_LIMIT_REMAINING)
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _rate_limit_message(response: httpx2.Response) -> str:
    """配额耗尽时给出重置时间，并说明 token 能提高配额。"""
    message = "GitHub API 配额已耗尽"
    reset = _reset_time(response.headers.get(_RATE_LIMIT_RESET))
    if reset is not None:
        message = f"{message}，将于 {reset} 重置"
    retry_after = response.headers.get("retry-after")
    if retry_after is not None and retry_after.isdigit():
        message = f"{message}，请在 {retry_after} 秒后重试"
    return f"{message}；设置 GITHUB_TOKEN 可以提高配额"


def _reset_time(value: str | None) -> str | None:
    """把 X-RateLimit-Reset 的 Unix 秒解释成本地时间；读不懂就不显示。"""
    if value is None:
        return None
    try:
        moment = datetime.fromtimestamp(int(value), tz=UTC)
    except (ValueError, OSError, OverflowError):
        return None
    return moment.astimezone().strftime(_RESET_FORMAT)


def _payload(response: httpx2.Response) -> Mapping[str, object]:
    """解析响应体；超大、非 JSON、非对象都视为发现失败。

    httpx2 收完整个响应体之后才轮到我们，所以这里拦不住内存分配；它拦的是
    「把一个超限响应当正常结果继续解析并采信」。Content-Length 是廉价的先手，
    实际字节数是兜底 —— 那个头可能缺失或不可信。
    """
    if _declared_length(response) > _MAX_RESPONSE_BYTES or len(response.content) > _MAX_RESPONSE_BYTES:
        raise DiscoveryError("GitHub 响应超过大小上限")
    try:
        payload = response.json()
    except ValueError as error:
        raise DiscoveryError("GitHub 返回的内容不是合法 JSON") from error
    if not isinstance(payload, Mapping):
        raise DiscoveryError("GitHub 返回的 JSON 不是对象")
    return payload


def _declared_length(response: httpx2.Response) -> int:
    """Content-Length 声明的长度；缺失或不是纯数字时按 0 处理。"""
    raw = response.headers.get("content-length")
    return int(raw) if raw is not None and raw.isdigit() else 0


def _items(payload: Mapping[str, object]) -> tuple[Repository, ...]:
    raw_items = payload.get("items")
    if not isinstance(raw_items, list):
        raise DiscoveryError("GitHub 返回的 JSON 缺少 items 数组")
    return tuple(_repository(item) for item in raw_items)


def _repository(raw: object) -> Repository:
    """把一条搜索结果映射成值对象；关键字段缺失宁可失败也不生成半残条目。"""
    if not isinstance(raw, Mapping):
        raise DiscoveryError("GitHub 返回的仓库条目不是对象")
    return Repository(
        full_name=_required_text(raw, "full_name"),
        owner=_owner(raw),
        name=_required_text(raw, "name"),
        description=_optional_text(raw, "description"),
        stars=_non_negative(raw, "stargazers_count"),
        topics=_topics(raw),
        updated_at=_optional_text(raw, "updated_at") or "",
        default_branch=_optional_text(raw, "default_branch") or "",
        html_url=_required_text(raw, "html_url"),
        clone_url=_required_text(raw, "clone_url"),
        archived=_flag(raw, "archived"),
        disabled=_flag(raw, "disabled"),
    )


def _required_text(raw: Mapping[str, object], key: str) -> str:
    """关键文本字段；缺失、空白或类型不符都视为不可用的条目。"""
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise DiscoveryError(f"GitHub 返回的条目缺少字段 {key}")
    return value.strip()


def _optional_text(raw: Mapping[str, object], key: str) -> str | None:
    value = raw.get(key)
    return value.strip() if isinstance(value, str) and value.strip() else None


def _owner(raw: Mapping[str, object]) -> str:
    owner = raw.get("owner")
    login = owner.get("login") if isinstance(owner, Mapping) else None
    if not isinstance(login, str) or not login.strip():
        raise DiscoveryError("GitHub 返回的条目缺少字段 owner.login")
    return login.strip()


def _non_negative(raw: Mapping[str, object], key: str) -> int:
    """非负整数字段；缺失或类型不符时退回 0。"""
    value = raw.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return 0
    return value


def _flag(raw: Mapping[str, object], key: str) -> bool:
    """布尔字段；缺失按 false —— GitHub 没返回即视为未归档、未禁用。"""
    return raw.get(key) is True


def _topics(raw: Mapping[str, object]) -> tuple[str, ...]:
    """topic 只用于展示。准入依据是 Search API 的 query，不因它缺失丢弃结果。"""
    value = raw.get("topics")
    if not isinstance(value, list):
        return ()
    return tuple(item for item in value if isinstance(item, str))


__all__ = [
    "DEFAULT_ORDER",
    "DEFAULT_PAGE",
    "DEFAULT_PAGE_SIZE",
    "MAX_PAGE_SIZE",
    "MAX_RESULTS",
    "ORDER_FIELDS",
    "SORT_FIELDS",
    "TOPIC",
    "TOPIC_CLAUSE",
    "GitHubSource",
    "HttpTransport",
    "HttpxTransport",
    "build_search_query",
    "check_search_arguments",
]

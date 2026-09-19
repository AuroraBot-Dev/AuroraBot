"""``aurora app`` 的纯值对象、错误体系与输入校验。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from aurora.utils.toml import check_package_name

type AppState = Literal["ready", "missing", "invalid"]
type RepositoryStatus = Literal["active", "archived", "disabled"]


class AppError(RuntimeError):
    """可直接转换为中文 CLI 失败结果的 App 管理错误。"""


class ConfigError(AppError):
    """输入或配置不合法：注册表缺失或无法解析，或命令行参数越界。"""


class RegistryError(AppError):
    """注册表结构不合法，例如 app 不是表数组，或 package 缺失、非法、重复。"""


class RegistryWriteError(RegistryError):
    """注册表写入失败；原文件保持不变。"""


class PackageError(AppError):
    """package ID 不是小写点分包名。"""


class AppNotFoundError(AppError):
    """注册表中不存在该 package。"""


class PathError(AppError):
    """working_dir 不是可安全使用的项目内路径。"""


class DiscoveryError(AppError):
    """GitHub 仓库发现失败。

    消息里绝不允许出现请求头、``Authorization`` 或 token —— 见第二阶段方案
    第十七节，错误信息会被直接打印给用户。
    """


class GitHubRateLimitError(DiscoveryError):
    """GitHub API 配额耗尽；携带重置时间或 Retry-After。"""


@dataclass(frozen=True, slots=True)
class AppListItem:
    """注册表中的一个 App 及其相对本机文件系统的事实。

    ``state`` 为 ``ready`` 只表示该条目自身可用，不表示 App 正在运行，也不表示
    远程 Server 在线；``path`` 对 stdio 是声明的 working_dir，对其余传输为 None。
    """

    package: str
    enabled: bool
    transport: str
    state: AppState
    path: str | None


@dataclass(frozen=True, slots=True)
class AppList:
    """一次注册表读取的结果。"""

    apps: tuple[AppListItem, ...]


@dataclass(frozen=True, slots=True)
class Repository:
    """GitHub 上的一个候选仓库。

    带 aurorabot-app topic 只说明它是候选，不说明它是 MCP Server：本阶段不
    clone、不检查、不连接。字段集覆盖后续 install 需要的部分，避免下一阶段
    再改这个值对象。
    """

    full_name: str
    owner: str
    name: str
    description: str | None
    stars: int
    topics: tuple[str, ...]
    updated_at: str
    default_branch: str
    html_url: str
    clone_url: str
    archived: bool
    disabled: bool

    @property
    def status(self) -> RepositoryStatus:
        """展示用状态；被禁用优先于被归档，两者都不适合安装。"""
        if self.disabled:
            return "disabled"
        return "archived" if self.archived else "active"


@dataclass(frozen=True, slots=True)
class RepositoryPage:
    """一页 GitHub 搜索结果。"""

    items: tuple[Repository, ...]
    page: int
    page_size: int
    total_count: int
    incomplete_results: bool


def validate_package(value: str) -> str:
    """校验并返回 package ID；与运行时 AppConfig 使用同一条包名规则。"""
    try:
        check_package_name(value, "app.package")
    except ValueError as error:
        raise PackageError(f"package ID 必须是小写点分包名：{value}") from error
    return value


def registry_package(value: object, label: str) -> str:
    """校验注册表里的 package 字段；package 本身的问题让整次读取失败。"""
    if not isinstance(value, str) or not value.strip():
        raise RegistryError(f"{label} 的 package 必须是非空文本")
    try:
        return validate_package(value.strip())
    except PackageError as error:
        raise RegistryError(f"{label} 的 {error}") from error


__all__ = [
    "AppError",
    "AppList",
    "AppListItem",
    "AppNotFoundError",
    "AppState",
    "ConfigError",
    "DiscoveryError",
    "GitHubRateLimitError",
    "PackageError",
    "PathError",
    "RegistryError",
    "RegistryWriteError",
    "Repository",
    "RepositoryPage",
    "RepositoryStatus",
    "registry_package",
    "validate_package",
]

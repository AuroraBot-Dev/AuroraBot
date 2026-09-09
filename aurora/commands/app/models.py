"""Aurora MCP App 包管理的纯值对象与输入规范化。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime
    from pathlib import Path

_REPOSITORY = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9_.-]{0,98}[A-Za-z0-9])?/[A-Za-z0-9_.-]{1,100}")


class AppManagerError(RuntimeError):
    """可直接转换为中文 CLI 失败结果的 App 管理错误。"""


class AppManagerConfigError(AppManagerError):
    """个人 apps.toml 缺失或无效。"""


@dataclass(frozen=True, slots=True)
class Repository:
    """GitHub 仓库搜索和安装需要的稳定字段。"""

    full_name: str
    description: str
    stars: int
    default_branch: str
    html_url: str
    clone_url: str
    topics: tuple[str, ...]
    archived: bool
    disabled: bool
    updated_at: str


@dataclass(frozen=True, slots=True)
class RepositoryPage:
    """一页 GitHub 仓库搜索结果。"""

    total: int
    page: int
    page_size: int
    incomplete: bool
    repositories: tuple[Repository, ...]


@dataclass(frozen=True, slots=True)
class AppManifest:
    """已经通过现有 AppConfig 规则校验的安装清单。"""

    package: str
    name: str
    version: str
    description: str
    command: tuple[str, ...]
    env: tuple[str, ...]
    timeout_seconds: float
    event_mode: str


@dataclass(frozen=True, slots=True)
class InstallMarker:
    """受管安装目录内由 Aurora 生成的所有权标记。"""

    package: str
    name: str
    version: str
    repository: str
    requested_ref: str
    resolved_commit: str
    installed_at: datetime


@dataclass(frozen=True, slots=True)
class InstalledApp:
    """受管安装与个人配置交叉检查后的列表项。"""

    path: Path
    state: str
    marker: InstallMarker | None = None
    enabled: bool | None = None
    detail: str | None = None

    @property
    def package(self) -> str:
        return self.marker.package if self.marker is not None else "-"


@dataclass(frozen=True, slots=True)
class InstalledAppList:
    """受管安装列表及写事务是否正在进行。"""

    apps: tuple[InstalledApp, ...]
    changing: bool


def normalize_repository(source: str) -> str:
    """把 owner/repo 或标准 GitHub HTTPS URL 规范化为仓库标识。"""
    value = source.strip().removesuffix("/").removesuffix(".git")
    prefix = "https://github.com/"
    if value.lower().startswith(prefix):
        value = value[len(prefix) :]
    if _REPOSITORY.fullmatch(value) is None:
        raise AppManagerError("仓库必须是 owner/repo 或 https://github.com/owner/repo")
    return value


__all__ = [
    "AppManagerConfigError",
    "AppManagerError",
    "AppManifest",
    "InstallMarker",
    "InstalledApp",
    "InstalledAppList",
    "Repository",
    "RepositoryPage",
    "normalize_repository",
]

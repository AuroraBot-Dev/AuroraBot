"""Aurora MCP App 的发现与受管安装。"""

from aurora.apps.github import GitHubClient, JsonResponse, JsonTransport
from aurora.apps.models import (
    AppManagerConfigError,
    AppManagerError,
    AppManifest,
    InstalledApp,
    InstalledAppList,
    InstallMarker,
    Repository,
    RepositoryPage,
    normalize_repository,
)
from aurora.apps.service import AppManager, CloneRepository

__all__ = [
    "AppManager",
    "AppManagerConfigError",
    "AppManagerError",
    "AppManifest",
    "CloneRepository",
    "GitHubClient",
    "InstallMarker",
    "InstalledApp",
    "InstalledAppList",
    "JsonResponse",
    "JsonTransport",
    "Repository",
    "RepositoryPage",
    "normalize_repository",
]

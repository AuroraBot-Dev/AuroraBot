"""Aurora MCP App 搜索、安装、列表和移除的用例编排。"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import tempfile
from collections.abc import Callable
from contextlib import suppress
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlsplit
from uuid import uuid4

from aurora.commands.app.discovery import discover_install
from aurora.commands.app.github import GitHubClient
from aurora.commands.app.manifest import load_manifest, manifest_app_config
from aurora.commands.app.models import (
    AppManagerError,
    AppManifest,
    InstalledApp,
    InstalledAppList,
    InstallMarker,
    Repository,
    RepositoryPage,
    normalize_repository,
)
from aurora.commands.app.store import MANIFEST_NAME, MARKER_NAME, AppStore, write_marker

if TYPE_CHECKING:
    from aurora.configuration.apps import AppConfig

_CONTROL_CODE_BOUNDARY = 32
_MIN_COMMIT_LENGTH = 7
_GIT_TIMEOUT_SECONDS = 300

type CloneRepository = Callable[[str, Path, str | None], str]
type Clock = Callable[[], datetime]
type ConfigureInstall = Callable[[Path, Repository], AppManifest]


class AppManager:
    """组合 GitHub、Git 与项目内文件边界的同步 App 管理服务。"""

    def __init__(
        self,
        project_root: Path,
        *,
        github: GitHubClient | None = None,
        clone: CloneRepository | None = None,
        clock: Clock | None = None,
        configure: ConfigureInstall | None = None,
    ) -> None:
        self.store = AppStore(project_root)
        self._github = github or GitHubClient(token=os.environ.get("GITHUB_TOKEN"))
        self._clone = clone or _clone_repository
        self._clock = clock or (lambda: datetime.now(UTC))
        self._configure = configure

    def search(
        self,
        *,
        query: str = "",
        page: int = 1,
        page_size: int = 20,
        sort: str = "stars",
        order: str = "desc",
    ) -> RepositoryPage:
        return self._github.search(query=query, page=page, page_size=page_size, sort=sort, order=order)

    def install(
        self, source: str, *, ref: str | None = None, enabled: bool = True, reuse_config: bool = False
    ) -> InstalledApp:
        identifier = normalize_repository(source)
        requested_ref = _validate_ref(ref) if ref is not None else None
        with self.store.lock("install"):
            self.store.apps_config()
            repository = self._github.repository(identifier)
            _validate_repository(repository)
            destination = self.store.destination(repository.full_name)
            if os.path.lexists(destination):
                raise AppManagerError(f"安装目录已存在：{destination.relative_to(self.store.project_root)}")
            if self.store.repository_installed(repository.full_name):
                raise AppManagerError(f"仓库已经安装：{repository.full_name}")
            return self._install(repository, destination, requested_ref, enabled, reuse_config)

    def list(self) -> InstalledAppList:
        return self.store.list_installed()

    def remove(self, package: str) -> InstalledApp:
        if not package.strip():
            raise AppManagerError("package ID 不能为空")
        with self.store.lock("remove"):
            matching = [item for item in self.store.list_installed().apps if item.package == package]
            if not matching:
                raise AppManagerError(f"未找到受管安装：{package}")
            if len(matching) != 1:
                raise AppManagerError(f"发现重复受管安装：{package}")
            installed = matching[0]
            if installed.state != "ready" or installed.marker is None:
                raise AppManagerError(f"安装状态不是 ready，拒绝移除：{package}/{installed.state}")
            return self._remove(installed)

    def _install(
        self,
        repository: Repository,
        destination: Path,
        ref: str | None,
        enabled: bool,
        reuse_config: bool,
    ) -> InstalledApp:
        try:
            self.store.install_root.mkdir(parents=True, exist_ok=True)
            staging = Path(tempfile.mkdtemp(prefix=".aurora-stage-", dir=self.store.install_root))
        except OSError as error:
            raise AppManagerError(f"无法创建安装临时目录：{error}") from error
        checkout = staging / "checkout"
        published = False
        configured = False
        try:
            commit = _validate_commit(self._clone(repository.clone_url, checkout, ref))
            working_dir = self.store.relative_working_dir(destination)
            manifest = self._manifest(checkout, repository, working_dir, enabled, reuse_config)
            previous, app_config = self._install_config(manifest, working_dir, enabled, reuse_config)
            if any(
                item.marker is not None and item.marker.package == manifest.package
                for item in self.store.list_installed().apps
            ):
                raise AppManagerError(f"受管安装已存在 package：{manifest.package}")
            marker = InstallMarker(
                manifest.package,
                manifest.name,
                manifest.version,
                repository.full_name,
                ref or repository.default_branch,
                commit,
                self._clock(),
            )
            write_marker(checkout / MARKER_NAME, marker)
            destination.parent.mkdir(parents=True, exist_ok=True)
            checkout.replace(destination)
            published = True
            if previous is None:
                self.store.add_app(app_config)
            else:
                self.store.reuse_app(previous, app_config)
            configured = True
            return InstalledApp(destination, "ready", marker=marker, enabled=app_config.enabled)
        except AppManagerError:
            raise
        except OSError as error:
            raise AppManagerError(f"安装文件操作失败：{error}") from error
        finally:
            if published and not configured:
                try:
                    destination.replace(checkout)
                except OSError as error:
                    raise AppManagerError(f"安装失败且目录回滚失败：{destination}：{error}") from error
            with suppress(OSError):
                shutil.rmtree(staging, onexc=_remove_readonly)
            with suppress(OSError):
                destination.parent.rmdir()

    def _manifest(
        self, checkout: Path, repository: Repository, working_dir: str, enabled: bool, reuse_config: bool
    ) -> AppManifest:
        path = checkout / MANIFEST_NAME
        if not os.path.lexists(path) and reuse_config:
            suggestions = discover_install(checkout, repository)
            matches = [
                app
                for app in self.store.apps_config()
                if app.transport == "stdio" and app.command in suggestions.commands
            ]
            if len(matches) != 1:
                raise AppManagerError(
                    "无法唯一匹配已有配置的启动命令；请补充安装清单以明确 package，或检查 apps.toml。"
                )
            app = matches[0]
            return AppManifest(
                app.package,
                suggestions.name,
                suggestions.version,
                suggestions.description,
                app.command,
                app.env,
                app.timeout_seconds,
                app.event_mode,
            )
        if os.path.lexists(path) or self._configure is None:
            return load_manifest(path, working_dir=working_dir, enabled=enabled)
        manifest = self._configure(checkout, repository)
        try:
            manifest_app_config(manifest, working_dir=working_dir, enabled=enabled)
        except ValueError as error:
            raise AppManagerError(f"无效安装配置：{error}") from error
        return manifest

    def _install_config(
        self, manifest: AppManifest, working_dir: str, enabled: bool, reuse_config: bool
    ) -> tuple[AppConfig | None, AppConfig]:
        existing = next((app for app in self.store.apps_config() if app.package == manifest.package), None)
        if existing is None:
            if reuse_config:
                raise AppManagerError(f"apps.toml 中未找到可复用的 package：{manifest.package}")
            return None, manifest_app_config(manifest, working_dir=working_dir, enabled=enabled)
        if not reuse_config:
            raise AppManagerError(
                f"apps.toml 已存在 package：{manifest.package}；若要保留该条目的配置并安装仓库，请加 --reuse-config。"
            )
        if existing.transport != "stdio" or existing.working_dir is None:
            raise AppManagerError(f"只能复用 stdio 配置：{manifest.package}")
        self.store.ensure_no_links(self.store.project_root / existing.working_dir)
        if os.path.lexists(self.store.project_root / existing.working_dir):
            raise AppManagerError(f"已有配置的工作目录已存在，拒绝覆盖：{existing.working_dir}")
        return existing, replace(existing, working_dir=working_dir, enabled=existing.enabled and enabled)

    def _remove(self, installed: InstalledApp) -> InstalledApp:
        directory = installed.path.resolve()
        self.store.ensure_managed_path(directory)
        quarantine = self.store.install_root / f".aurora-remove-{uuid4().hex}"
        try:
            directory.replace(quarantine)
        except OSError as error:
            raise AppManagerError(f"无法隔离安装目录：{error}") from error
        try:
            self.store.remove_app(installed.package, directory)
        except (AppManagerError, OSError, KeyboardInterrupt):
            try:
                quarantine.replace(directory)
            except OSError as rollback_error:
                raise AppManagerError(f"移除失败且目录回滚失败：{rollback_error}") from rollback_error
            raise
        try:
            shutil.rmtree(quarantine, onexc=_remove_readonly)
        except OSError as error:
            raise AppManagerError(f"配置已移除，但隔离目录清理失败：{quarantine}：{error}") from error
        with suppress(OSError):
            directory.parent.rmdir()
        return installed


def _remove_readonly(function: Callable[[str], object], path: str, error: BaseException) -> None:
    """仅重试 Windows 只读普通路径；真实权限错误继续上报。"""
    target = Path(path)
    if os.name != "nt" or not isinstance(error, PermissionError) or target.is_symlink() or target.is_junction():
        raise error
    mode = target.stat().st_mode
    if mode & stat.S_IWRITE:
        raise error
    target.chmod(mode | stat.S_IWRITE)
    function(path)


def _validate_repository(repository: Repository) -> None:
    if repository.archived:
        raise AppManagerError(f"仓库已归档：{repository.full_name}")
    if repository.disabled:
        raise AppManagerError(f"仓库已被 GitHub 禁用：{repository.full_name}")
    parsed = urlsplit(repository.clone_url)
    expected_path = f"/{repository.full_name}.git"
    if (
        parsed.scheme != "https"
        or parsed.hostname != "github.com"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path.casefold() != expected_path.casefold()
    ):
        raise AppManagerError(f"仓库 clone URL 不受支持：{repository.full_name}")


def _validate_ref(ref: str) -> str:
    value = ref.strip()
    if not value or value.startswith("-") or any(ord(character) < _CONTROL_CODE_BOUNDARY for character in value):
        raise AppManagerError("ref 必须是非空 Git branch 或 tag")
    return value


def _clone_repository(url: str, destination: Path, ref: str | None) -> str:
    disabled_hooks = destination.parent / ".hooks-disabled"
    disabled_hooks.mkdir()
    command = ["git", "-c", f"core.hooksPath={disabled_hooks}", "clone", "--depth", "1"]
    if ref is not None:
        command.extend(("--branch", ref, "--single-branch"))
    command.extend((url, str(destination)))
    _run_git(command, destination.parent, "Git 克隆失败")
    result = _run_git(
        ["git", "-C", str(destination), "rev-parse", "HEAD"],
        destination.parent,
        "无法读取安装 commit",
        capture=True,
    )
    return _validate_commit(result.stdout.strip())


def _validate_commit(commit: str) -> str:
    if len(commit) < _MIN_COMMIT_LENGTH or any(character not in "0123456789abcdefABCDEF" for character in commit):
        raise AppManagerError("Git 返回了无效 commit")
    return commit.lower()


def _run_git(
    command: list[str],
    directory: Path,
    label: str,
    *,
    capture: bool = False,
) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            command,
            cwd=directory,
            check=False,
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_SECONDS,
        )
    except FileNotFoundError as error:
        raise AppManagerError("未找到 git，请先安装并加入 PATH") from error
    except subprocess.TimeoutExpired as error:
        raise AppManagerError(f"{label}，超过 {_GIT_TIMEOUT_SECONDS} 秒") from error
    except OSError as error:
        raise AppManagerError(f"{label}，无法启动 git：{error}") from error
    if result.returncode != 0:
        raise AppManagerError(f"{label}，退出码 {result.returncode}")
    if not capture:
        return result
    return result


__all__ = ["AppManager"]

"""受管 App 目录、安装标记、写锁与 apps.toml 原子编辑。"""

from __future__ import annotations

import json
import os
import tempfile
import tomllib
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import tomlkit
from tomlkit.exceptions import ParseError
from tomlkit.items import AoT, Array

from aurora.apps.models import (
    AppManagerConfigError,
    AppManagerError,
    InstalledApp,
    InstalledAppList,
    InstallMarker,
    normalize_repository,
)
from aurora.configuration.apps import AppConfig, AppsConfig, load_apps_config

MANIFEST_NAME = "aurora-app.toml"
MARKER_NAME = ".aurora-installed.toml"
LOCK_NAME = ".aurora-app.lock"
_MARKER_FIELDS = frozenset(
    {
        "marker_version",
        "package",
        "name",
        "version",
        "repository",
        "requested_ref",
        "resolved_commit",
        "installed_at",
    }
)
_MANAGED_PATH_DEPTH = 2
_MIN_COMMIT_LENGTH = 7


class AppWriteLock:
    """使用原子目录创建串行化同一项目的 install/remove。"""

    def __init__(self, install_root: Path, operation: str) -> None:
        self.path = install_root / LOCK_NAME
        self._operation = operation
        self._owned = False

    def __enter__(self) -> AppWriteLock:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.mkdir()
        except FileExistsError as error:
            detail = _lock_detail(self.path)
            raise AppManagerError(f"另一个 App 写操作正在进行{detail}") from error
        except OSError as error:
            raise AppManagerError(f"无法创建 App 写锁：{error}") from error
        self._owned = True
        try:
            metadata = {
                "pid": os.getpid(),
                "operation": self._operation,
                "created_at": datetime.now(UTC).isoformat(),
            }
            (self.path / "owner.json").write_text(json.dumps(metadata, ensure_ascii=False), encoding="utf-8")
        except OSError as error:
            self.__exit__(None, None, None)
            raise AppManagerError(f"无法写入 App 写锁：{error}") from error
        return self

    def __exit__(self, error_type: object, error: object, traceback: object) -> None:
        if not self._owned:
            return
        with suppress(OSError):
            (self.path / "owner.json").unlink(missing_ok=True)
        with suppress(OSError):
            self.path.rmdir()
        self._owned = False


class AppStore:
    """项目内受管安装和个人 App 配置的唯一文件边界。"""

    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root.resolve()
        self.install_root = self.project_root / "extensions" / "apps"
        self.apps_path = self.project_root / "config" / "apps.toml"

    def lock(self, operation: str) -> AppWriteLock:
        self.ensure_install_root_safe()
        return AppWriteLock(self.install_root, operation)

    def destination(self, repository: str) -> Path:
        self.ensure_install_root_safe()
        owner, name = normalize_repository(repository).split("/", maxsplit=1)
        lexical_destination = self.install_root / owner / name
        self.ensure_no_links(lexical_destination)
        destination = lexical_destination.resolve()
        self.ensure_managed_path(destination)
        return destination

    def relative_working_dir(self, destination: Path) -> str:
        self.ensure_managed_path(destination.resolve())
        return destination.resolve().relative_to(self.project_root).as_posix()

    def apps_config(self) -> AppsConfig:
        if not self.apps_path.is_file():
            raise AppManagerConfigError("未找到 config/apps.toml，请先运行 aurora setup")
        try:
            return load_apps_config(self.apps_path)
        except (OSError, tomllib.TOMLDecodeError, ValueError) as error:
            raise AppManagerConfigError(f"apps.toml 无效：{error}") from error

    def add_app(self, app: AppConfig) -> None:
        config = self.apps_config()
        if any(current.package == app.package for current in config.apps):
            raise AppManagerError(f"apps.toml 已存在 package：{app.package}")
        document, entries, empty_array_comment = self._document()
        table = tomlkit.table()
        if empty_array_comment is not None:
            table.comment(empty_array_comment)
        table.add("package", app.package)
        table.add("enabled", app.enabled)
        table.add("transport", app.transport)
        assert app.working_dir is not None
        table.add("working_dir", app.working_dir)
        table.add("command", list(app.command))
        table.add("env", list(app.env))
        table.add("timeout_seconds", app.timeout_seconds)
        table.add("event_mode", app.event_mode)
        entries.append(table)
        _atomic_write(self.apps_path, tomlkit.dumps(document))

    def remove_app(self, package: str, expected_directory: Path) -> None:
        config = self.apps_config()
        matching = [app for app in config.apps if app.package == package]
        if len(matching) != 1:
            raise AppManagerError(f"apps.toml 中 package 数量异常：{package}")
        app = matching[0]
        if app.working_dir is None or (self.project_root / app.working_dir).resolve() != expected_directory.resolve():
            raise AppManagerError(f"apps.toml 工作目录不匹配：{package}")
        document, entries, _empty_array_comment = self._document()
        indexes = [index for index, item in enumerate(entries) if item.get("package") == package]
        if len(indexes) != 1:
            raise AppManagerError(f"apps.toml 中 package 数量异常：{package}")
        del entries[indexes[0]]
        _atomic_write(self.apps_path, tomlkit.dumps(document))

    def list_installed(self) -> InstalledAppList:
        self.ensure_install_root_safe()
        configured = {app.package: app for app in self.apps_config().apps}
        apps: list[InstalledApp] = []
        for directory in self._candidate_directories():
            marker_path = directory / MARKER_NAME
            try:
                self.ensure_managed_path(directory.resolve())
                if _is_link(directory) or _is_link(marker_path):
                    raise AppManagerError(f"受管安装不得使用符号链接：{directory}")
                if not marker_path.exists():
                    continue
                marker = read_marker(marker_path)
            except (AppManagerError, OSError, tomllib.TOMLDecodeError) as error:
                apps.append(InstalledApp(directory, "invalid_marker", detail=str(error)))
                continue
            relative_repository = "/".join(directory.resolve().relative_to(self.install_root.resolve()).parts)
            if relative_repository.casefold() != marker.repository.casefold():
                apps.append(
                    InstalledApp(
                        directory,
                        "config_mismatch",
                        marker=marker,
                        detail="repository 与安装目录不一致",
                    )
                )
                continue
            app = configured.get(marker.package)
            if app is None:
                if any(
                    current.working_dir is not None
                    and (self.project_root / current.working_dir).resolve() == directory.resolve()
                    for current in configured.values()
                ):
                    apps.append(InstalledApp(directory, "config_mismatch", marker=marker, detail="package 不一致"))
                    continue
                apps.append(InstalledApp(directory, "config_missing", marker=marker))
                continue
            configured_path = (
                (self.project_root / app.working_dir).resolve() if app.working_dir is not None else self.project_root
            )
            if configured_path != directory.resolve():
                apps.append(
                    InstalledApp(
                        directory, "config_mismatch", marker=marker, enabled=app.enabled, detail="working_dir 不一致"
                    )
                )
                continue
            apps.append(InstalledApp(directory, "ready", marker=marker, enabled=app.enabled))
        return InstalledAppList(
            tuple(sorted(apps, key=lambda item: (item.package, str(item.path)))), self.lock_exists()
        )

    def repository_installed(self, repository: str) -> bool:
        target = normalize_repository(repository).casefold()
        return any(
            item.marker is not None and item.marker.repository.casefold() == target
            for item in self.list_installed().apps
        )

    def lock_exists(self) -> bool:
        return (self.install_root / LOCK_NAME).is_dir()

    def ensure_managed_path(self, directory: Path) -> None:
        self.ensure_install_root_safe()
        root = self.install_root.resolve()
        if directory == root or not directory.is_relative_to(root):
            raise AppManagerError(f"受管安装目录越界：{directory}")
        if len(directory.relative_to(root).parts) != _MANAGED_PATH_DEPTH:
            raise AppManagerError(f"受管安装目录层级无效：{directory}")

    def ensure_install_root_safe(self) -> None:
        """确认安装根位于项目内，且现有路径组件均不是链接或联接。"""
        self.ensure_no_links(self.install_root)
        root = self.install_root.resolve()
        if root == self.project_root or not root.is_relative_to(self.project_root):
            raise AppManagerError(f"App 安装根目录越界：{self.install_root}")

    def ensure_no_links(self, path: Path) -> None:
        try:
            relative = path.relative_to(self.project_root)
        except ValueError as error:
            raise AppManagerError(f"受管安装目录越界：{path}") from error
        current = self.project_root
        for part in relative.parts:
            current /= part
            if os.path.lexists(current) and _is_link(current):
                raise AppManagerError(f"受管安装路径不得使用符号链接或联接：{current}")

    def _candidate_directories(self) -> tuple[Path, ...]:
        if not self.install_root.is_dir():
            return ()
        directories: list[Path] = []
        for owner in self.install_root.iterdir():
            if owner.name.startswith(".") or _is_link(owner) or not owner.is_dir():
                continue
            for repository in owner.iterdir():
                if repository.is_dir():
                    directories.append(repository)
        return tuple(directories)

    def _document(self) -> tuple[tomlkit.TOMLDocument, AoT, str | None]:
        try:
            document = tomlkit.parse(self.apps_path.read_text(encoding="utf-8"))
        except (OSError, ParseError) as error:
            raise AppManagerConfigError(f"apps.toml 无效：{error}") from error
        entries = document.get("app")
        if isinstance(entries, AoT):
            return document, entries, None
        if isinstance(entries, Array) and not entries:
            comment = entries.trivia.comment.removeprefix("#").strip() or None
            table_array = tomlkit.aot()
            document["app"] = table_array
            return document, table_array, comment
        raise AppManagerConfigError("apps.toml 的 app 必须是表数组")


def write_marker(path: Path, marker: InstallMarker) -> None:
    """写入安装器保留标记；仓库已有同名文件时拒绝覆盖。"""
    if os.path.lexists(path):
        raise AppManagerError(f"仓库包含保留文件：{MARKER_NAME}")
    document = tomlkit.document()
    document.add("marker_version", 1)
    document.add("package", marker.package)
    document.add("name", marker.name)
    document.add("version", marker.version)
    document.add("repository", marker.repository)
    document.add("requested_ref", marker.requested_ref)
    document.add("resolved_commit", marker.resolved_commit)
    document.add("installed_at", marker.installed_at.astimezone(UTC).isoformat())
    path.write_text(tomlkit.dumps(document), encoding="utf-8", newline="\n")


def read_marker(path: Path) -> InstallMarker:
    """严格读取一个受管安装标记。"""
    with path.open("rb") as stream:
        document = tomllib.load(stream)
    names = set(document)
    marker_version = document.get("marker_version")
    if (
        names != _MARKER_FIELDS
        or not isinstance(marker_version, int)
        or isinstance(marker_version, bool)
        or marker_version != 1
    ):
        raise AppManagerError(f"安装标记无效：{path}")
    installed_at = _marker_text(document, "installed_at")
    try:
        when = datetime.fromisoformat(installed_at)
    except ValueError as error:
        raise AppManagerError(f"安装标记时间无效：{path}") from error
    if when.tzinfo is None:
        raise AppManagerError(f"安装标记时间缺少时区：{path}")
    commit = _marker_text(document, "resolved_commit")
    if len(commit) < _MIN_COMMIT_LENGTH or any(character not in "0123456789abcdefABCDEF" for character in commit):
        raise AppManagerError(f"安装标记 commit 无效：{path}")
    return InstallMarker(
        _marker_text(document, "package"),
        _marker_text(document, "name"),
        _marker_text(document, "version"),
        normalize_repository(_marker_text(document, "repository")),
        _marker_text(document, "requested_ref"),
        commit.lower(),
        when.astimezone(UTC),
    )


def _marker_text(document: dict[str, Any], key: str) -> str:
    value = document.get(key)
    if not isinstance(value, str) or not value.strip():
        raise AppManagerError(f"安装标记字段 {key} 必须是非空文本")
    return value.strip()


def _atomic_write(path: Path, content: str) -> None:
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _lock_detail(path: Path) -> str:
    try:
        payload = json.loads((path / "owner.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    operation = payload.get("operation")
    pid = payload.get("pid")
    if isinstance(operation, str) and isinstance(pid, int):
        return f"（{operation}，PID {pid}）"
    return ""


def _is_link(path: Path) -> bool:
    return path.is_symlink() or path.is_junction()


__all__ = [
    "LOCK_NAME",
    "MANIFEST_NAME",
    "MARKER_NAME",
    "AppStore",
    "AppWriteLock",
    "read_marker",
    "write_marker",
]

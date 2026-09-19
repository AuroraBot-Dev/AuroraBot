"""``config/apps.toml`` 的唯一读写边界：注册表读取、原子写与路径安全。"""

from __future__ import annotations

import os
import stat
import tempfile
import tomllib
from contextlib import suppress
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, cast

import tomlkit
from tomlkit.exceptions import ParseError
from tomlkit.items import AoT, Array, Table

from aurora.commands.app.models import (
    AppList,
    AppListItem,
    AppNotFoundError,
    AppState,
    ConfigError,
    PathError,
    RegistryError,
    RegistryWriteError,
    registry_package,
)
from aurora.utils.toml import (
    TomlTable,
    boolean,
    check_relative_directory,
    check_unique_items,
    load_toml,
    optional_text,
    positive_number,
    strings,
    table_array,
    text,
)
from src.mcp.config import AppConfig, McpEventMode, McpTransport

if TYPE_CHECKING:
    from tomlkit.toml_document import TOMLDocument

APPS_RELATIVE_PATH = "config/apps.toml"


class AppStore:
    """``config/apps.toml`` 的读取、修改与路径安全边界。"""

    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root.resolve()
        self.apps_path = self.project_root / APPS_RELATIVE_PATH

    def list_apps(self) -> AppList:
        """正向读取注册表并核对每个条目自身的 working_dir；不反向扫描磁盘。"""
        raw_apps = _raw_apps(self._read_document())
        packages = _packages(raw_apps)
        items = tuple(self._item(package, raw) for package, raw in zip(packages, raw_apps, strict=True))
        return AppList(items)

    def set_enabled(self, package: str, enabled: bool) -> bool:
        """修改一个已有条目的 enabled；返回是否实际改动了文件。"""
        if not self.apps_path.is_file():
            raise _missing_registry(self.apps_path)
        return self._set_enabled(package, enabled)

    def validate_registered_working_dir(self, working_dir: str) -> Path:
        """校验已注册 App 的 working_dir，返回项目内的绝对路径。

        事务目录（暂存、回收）不适用这条规则，它们会有各自的校验入口。
        """
        try:
            check_relative_directory(working_dir, "app.working_dir")
        except ValueError as error:
            raise PathError(f"working_dir 必须是项目内相对目录：{working_dir}") from error
        normalized = PurePosixPath(working_dir.replace("\\", "/"))
        directory = self.project_root.joinpath(*normalized.parts)
        for component in _components(self.project_root, directory):
            if os.path.lexists(component) and (component.is_symlink() or component.is_junction()):
                raise PathError(f"working_dir 不得经过符号链接或联接：{component}")
        if not directory.resolve().is_relative_to(self.project_root):
            raise PathError(f"working_dir 越出项目根目录：{working_dir}")
        return directory

    def _read_document(self) -> TomlTable:
        if not self.apps_path.is_file():
            raise _missing_registry(self.apps_path)
        try:
            return load_toml(self.apps_path)
        except (OSError, tomllib.TOMLDecodeError) as error:
            raise ConfigError(f"{APPS_RELATIVE_PATH} 无法解析：{error}") from error

    def _item(self, package: str, raw: TomlTable) -> AppListItem:
        """把一个条目投影成列表项；条目字段问题只影响它自己，不影响整次读取。"""
        transport = _declared_text(raw, "transport")
        config = _app_config(package, raw)
        if config is None:
            return AppListItem(package, False, transport, "invalid", _declared_text(raw, "working_dir"))
        if config.transport == "stdio" and config.working_dir is not None:
            state = self._stdio_state(config.working_dir)
            return AppListItem(package, config.enabled, "stdio", state, config.working_dir)
        return AppListItem(package, config.enabled, config.transport, "ready", None)

    def _stdio_state(self, working_dir: str) -> AppState:
        try:
            directory = self.validate_registered_working_dir(working_dir)
        except PathError:
            return "invalid"
        return "ready" if directory.is_dir() else "missing"

    def _set_enabled(self, package: str, enabled: bool) -> bool:
        document = self._editable_document()
        matches = [entry for entry in _editable_apps(document) if entry.get("package") == package]
        if not matches:
            raise AppNotFoundError(f"注册表中不存在 package：{package}")
        if len(matches) > 1:
            raise RegistryError(f"{APPS_RELATIVE_PATH} 中 package 重复：{package}")
        entry = matches[0]
        current = entry.get("enabled")
        if isinstance(current, bool) and current is enabled:
            return False
        entry["enabled"] = enabled
        _atomic_write(self.apps_path, tomlkit.dumps(document))
        return True

    def _editable_document(self) -> TOMLDocument:
        try:
            return tomlkit.parse(self.apps_path.read_text(encoding="utf-8"))
        except (OSError, ParseError) as error:
            raise ConfigError(f"{APPS_RELATIVE_PATH} 无法解析：{error}") from error


def _missing_registry(path: Path) -> ConfigError:
    """config/ 是 git 忽略的个人配置，缺失时指向生成它的命令而不是模板。"""
    return ConfigError(
        f"未找到 {APPS_RELATIVE_PATH}：{path}；先运行 aurora setup 生成个人配置，或从 config.example/apps.toml 复制。"
    )


def _raw_apps(document: TomlTable) -> tuple[TomlTable, ...]:
    try:
        return table_array(document, "app")
    except ValueError as error:
        raise RegistryError(f"{APPS_RELATIVE_PATH} 无效：{error}") from error


def _packages(raw_apps: tuple[TomlTable, ...]) -> tuple[str, ...]:
    """读取全部 package 并检查唯一性；重复时无法确定该操作哪一个条目。"""
    packages = tuple(registry_package(raw.get("package"), APPS_RELATIVE_PATH) for raw in raw_apps)
    try:
        check_unique_items(packages, "app.package")
    except ValueError as error:
        repeated = sorted({package for package in packages if packages.count(package) > 1})
        raise RegistryError(f"{APPS_RELATIVE_PATH} 中 package 重复：{'、'.join(repeated)}") from error
    return packages


def _editable_apps(document: TOMLDocument) -> tuple[Table, ...]:
    """取出可编辑的 ``[[app]]`` 条目；空数组视为没有任何条目。"""
    entries = document.get("app")
    if isinstance(entries, AoT):
        return tuple(entries)
    if isinstance(entries, Array) and len(entries) == 0:
        return ()
    raise RegistryError(f"{APPS_RELATIVE_PATH} 的 app 必须是表数组")


def _declared_text(raw: TomlTable, key: str) -> str:
    """按注册表原样展示字段；缺失或非文本时用占位符。"""
    value = raw.get(key)
    return value.strip() if isinstance(value, str) and value.strip() else "-"


def _components(root: Path, path: Path) -> tuple[Path, ...]:
    """从项目根开始逐层枚举路径的每一级，用于检查链接与联接。"""
    try:
        relative = path.relative_to(root)
    except ValueError as error:
        raise PathError(f"working_dir 越出项目根目录：{path}") from error
    current = root
    components: list[Path] = []
    for part in relative.parts:
        current = current / part
        components.append(current)
    return tuple(components)


def _app_config(package: str, raw: TomlTable) -> AppConfig | None:
    """用运行时 AppConfig 校验单个条目；字段不合规时该条目为 invalid。"""
    try:
        return _build_app_config(package, raw)
    except (TypeError, ValueError):
        return None


def _build_app_config(package: str, raw: TomlTable) -> AppConfig:
    transport = cast("McpTransport", text(raw, "transport"))
    common = {
        "package": package,
        "enabled": boolean(raw, "enabled"),
        "transport": transport,
        "event_mode": cast("McpEventMode", optional_text(raw, "event_mode") or "disabled"),
        "timeout_seconds": positive_number(raw, "timeout_seconds"),
    }
    if transport == "stdio":
        return AppConfig(
            **common,
            working_dir=text(raw, "working_dir"),
            command=strings(raw, "command"),
            env=strings(raw, "env"),
        )
    return AppConfig(**common, url=text(raw, "url"), auth_env=optional_text(raw, "auth_env"))


def _atomic_write(path: Path, content: str) -> None:
    """同目录临时文件 + fsync + 原子替换；任一步失败都保留原文件。"""
    temporary = _write_temporary(path, content)
    try:
        _replace(temporary, path)
    except OSError as error:
        raise RegistryWriteError(f"无法写入 {path.name}：{error}{_discard(temporary)}") from error
    _discard(temporary)


def _write_temporary(path: Path, content: str) -> Path:
    """在目标同目录写入并落盘临时文件；跨文件系统的替换没有原子语义。"""
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        _copy_mode(path, temporary)
    except OSError as error:
        raise RegistryWriteError(f"无法写入 {path.name}：{error}{_discard(temporary)}") from error
    return temporary


def _replace(source: Path, target: Path) -> None:
    """原子替换；独立成函数以便测试注入失败路径。"""
    source.replace(target)


def _copy_mode(source: Path, target: Path) -> None:
    """让临时文件继承原文件权限，避免替换后文件权限发生变化。"""
    try:
        mode = stat.S_IMODE(source.stat().st_mode)
    except OSError:
        return
    with suppress(OSError):
        target.chmod(mode)


def _discard(path: Path) -> str:
    """删除临时文件；失败时返回残留路径提示，不改变主错误。"""
    try:
        path.unlink(missing_ok=True)
    except OSError:
        return f"；残留临时文件 {path}"
    return ""


__all__ = [
    "APPS_RELATIVE_PATH",
    "AppStore",
]

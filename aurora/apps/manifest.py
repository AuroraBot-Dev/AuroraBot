"""仓库根目录 ``aurora-app.toml`` 的严格解析。"""

from __future__ import annotations

import math
import tomllib
from collections.abc import Mapping
from typing import TYPE_CHECKING, cast

from aurora.apps.models import AppManagerError, AppManifest
from aurora.configuration.apps import AppConfig, McpEventMode

_ROOT_FIELDS = frozenset({"manifest_version", "package", "app"})
_PACKAGE_FIELDS = frozenset({"id", "name", "version", "description"})
_APP_FIELDS = frozenset({"command", "env", "timeout_seconds", "event_mode"})
_CONTROL_CODE_BOUNDARY = 32

if TYPE_CHECKING:
    from pathlib import Path


def load_manifest(path: Path, *, working_dir: str, enabled: bool) -> AppManifest:
    """解析清单并复用运行时 AppConfig 校验 stdio 字段。"""
    try:
        if path.is_symlink() or path.is_junction():
            raise AppManagerError("aurora-app.toml 必须是仓库根目录内的普通文件，不得使用链接或联接")
        resolved = path.resolve(strict=True)
        repository_root = path.parent.resolve(strict=True)
        if resolved.parent != repository_root or not resolved.is_file():
            raise AppManagerError("aurora-app.toml 必须是仓库根目录内的普通文件")
        with resolved.open("rb") as stream:
            document = tomllib.load(stream)
    except AppManagerError:
        raise
    except FileNotFoundError as error:
        raise AppManagerError("仓库根目录缺少 aurora-app.toml") from error
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise AppManagerError(f"无法读取 aurora-app.toml：{error}") from error
    _exact_fields(document, _ROOT_FIELDS, "aurora-app.toml")
    manifest_version = document.get("manifest_version")
    if not isinstance(manifest_version, int) or isinstance(manifest_version, bool) or manifest_version != 1:
        raise AppManagerError("aurora-app.toml manifest_version 必须是整数 1")
    package = _table(document, "package")
    app = _table(document, "app")
    _exact_fields(package, _PACKAGE_FIELDS, "package")
    _exact_fields(app, _APP_FIELDS, "app")
    version = _text(package, "version")
    if any(ord(character) < _CONTROL_CODE_BOUNDARY for character in version):
        raise AppManagerError("package.version 不得包含控制字符")
    timeout = app.get("timeout_seconds")
    if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or not math.isfinite(timeout) or timeout <= 0:
        raise AppManagerError("app.timeout_seconds 必须是有限正数")
    event_mode = _text(app, "event_mode")
    try:
        config = AppConfig(
            package=_text(package, "id"),
            enabled=enabled,
            transport="stdio",
            event_mode=cast("McpEventMode", event_mode),
            timeout_seconds=float(timeout),
            working_dir=working_dir,
            command=_strings(app, "command"),
            env=_strings(app, "env"),
        )
    except ValueError as error:
        raise AppManagerError(f"无效安装清单：{error}") from error
    return AppManifest(
        config.package,
        _text(package, "name"),
        version,
        _text(package, "description"),
        config.command,
        config.env,
        config.timeout_seconds,
        config.event_mode,
    )


def manifest_app_config(manifest: AppManifest, *, working_dir: str, enabled: bool) -> AppConfig:
    """把校验过的清单映射为现有运行时配置 DTO。"""
    return AppConfig(
        manifest.package,
        enabled,
        "stdio",
        cast("McpEventMode", manifest.event_mode),
        manifest.timeout_seconds,
        working_dir=working_dir,
        command=manifest.command,
        env=manifest.env,
    )


def _exact_fields(value: Mapping[str, object], expected: frozenset[str], label: str) -> None:
    names = set(value)
    if names != expected:
        raise AppManagerError(f"{label} 字段不匹配：未知 {sorted(names - expected)}，缺少 {sorted(expected - names)}")


def _table(value: Mapping[str, object], key: str) -> Mapping[str, object]:
    item = value.get(key)
    if not isinstance(item, Mapping):
        raise AppManagerError(f"{key} 必须是 TOML 表")
    return cast("Mapping[str, object]", item)


def _text(value: Mapping[str, object], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item.strip():
        raise AppManagerError(f"{key} 必须是非空文本")
    return item.strip()


def _strings(value: Mapping[str, object], key: str) -> tuple[str, ...]:
    item = value.get(key)
    if not isinstance(item, list) or any(not isinstance(part, str) for part in item):
        raise AppManagerError(f"{key} 必须是文本数组")
    return tuple(item)


__all__ = ["load_manifest", "manifest_app_config"]

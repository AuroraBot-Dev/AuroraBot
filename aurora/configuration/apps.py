"""解析并注册 ``config/apps.toml`` 的 MCP 应用定义。"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Literal, cast
from urllib.parse import urlsplit

from aurora.config import ConfigKey
from aurora.utils.toml import TomlTable, boolean, load_toml, text

if TYPE_CHECKING:
    from pathlib import Path

    from aurora.config import ConfigCollector

type McpTransport = Literal["stdio", "streamable_http"]
type McpEventMode = Literal["disabled", "world_events", "legacy_aurora_event"]

_TRANSPORTS = frozenset({"stdio", "streamable_http"})
_EVENT_MODES = frozenset({"disabled", "world_events", "legacy_aurora_event"})
_PACKAGE = re.compile(r"[a-z][a-z0-9_-]*(?:\.[a-z][a-z0-9_-]*)+")
_ENVIRONMENT_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_COMMON_FIELDS = frozenset({"package", "enabled", "transport", "timeout_seconds", "event_mode"})
_STDIO_FIELDS = _COMMON_FIELDS | {"working_dir", "command", "env"}
_HTTP_FIELDS = _COMMON_FIELDS | {"url", "auth_env"}
_WINDOWS_ABSOLUTE_MIN_LENGTH = 3


@dataclass(frozen=True, slots=True)
class AppConfig:
    """一个 MCP Server 的纯配置定义。"""

    package: str
    enabled: bool
    transport: McpTransport
    event_mode: McpEventMode
    timeout_seconds: float
    working_dir: str | None = None
    command: tuple[str, ...] = ()
    env: tuple[str, ...] = ()
    url: str | None = None
    auth_env: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "command", tuple(self.command))
        object.__setattr__(self, "env", tuple(self.env))
        if _PACKAGE.fullmatch(self.package) is None:
            raise ValueError("app.package 必须是小写点分包名")
        if not isinstance(self.enabled, bool):
            raise ValueError("app.enabled 必须是布尔值")
        if self.transport not in _TRANSPORTS:
            raise ValueError("app.transport 必须是 stdio 或 streamable_http")
        if self.event_mode not in _EVENT_MODES:
            raise ValueError("app.event_mode 不受支持")
        if (
            not isinstance(self.timeout_seconds, (int, float))
            or isinstance(self.timeout_seconds, bool)
            or not math.isfinite(self.timeout_seconds)
            or self.timeout_seconds <= 0
        ):
            raise ValueError("app.timeout_seconds 必须是有限正数")
        object.__setattr__(self, "timeout_seconds", float(self.timeout_seconds))
        if self.transport == "stdio":
            self._validate_stdio()
        else:
            self._validate_http()

    def _validate_stdio(self) -> None:
        if self.working_dir is None:
            raise ValueError("stdio app 必须声明 working_dir")
        _validate_relative_directory(self.working_dir)
        if not self.command or any(not isinstance(item, str) or not item.strip() for item in self.command):
            raise ValueError("stdio app.command 必须是非空文本数组")
        _validate_environment_names(self.env, "app.env")
        if self.url is not None or self.auth_env is not None:
            raise ValueError("stdio app 不得声明 url 或 auth_env")

    def _validate_http(self) -> None:
        if self.working_dir is not None or self.command or self.env:
            raise ValueError("streamable_http app 不得声明 working_dir、command 或 env")
        if self.url is None:
            raise ValueError("streamable_http app 必须声明 HTTPS url")
        _validate_https_url(self.url)
        if self.event_mode == "world_events":
            raise ValueError("streamable_http app 暂不支持 world_events")
        if self.auth_env is not None:
            _validate_environment_names((self.auth_env,), "app.auth_env")


@dataclass(frozen=True, slots=True)
class AppsConfig:
    """全部已配置 MCP App 的不可变目录。"""

    apps: tuple[AppConfig, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "apps", tuple(self.apps))
        packages = [app.package for app in self.apps]
        if len(packages) != len(set(packages)):
            raise ValueError("app.package 不得重复")


APPS_CONFIG = ConfigKey[AppsConfig]("apps")


def register(configs: ConfigCollector) -> None:
    configs.register(APPS_CONFIG, "config/apps.toml", _parse)


def _parse(path: Path) -> AppsConfig:
    document = load_toml(path)
    _require_fields(document, frozenset({"app"}), frozenset({"app"}), "apps.toml")
    raw_apps = document["app"]
    if not isinstance(raw_apps, (list, tuple)) or any(not isinstance(item, Mapping) for item in raw_apps):
        raise ValueError("apps.toml 的 app 必须是表数组")
    return AppsConfig(tuple(_parse_app(cast("TomlTable", item)) for item in raw_apps))


def _parse_app(raw: TomlTable) -> AppConfig:
    transport_value = text(raw, "transport")
    if transport_value not in _TRANSPORTS:
        raise ValueError("app.transport 必须是 stdio 或 streamable_http")
    transport = cast("McpTransport", transport_value)
    allowed = _STDIO_FIELDS if transport == "stdio" else _HTTP_FIELDS
    required = (_STDIO_FIELDS - {"event_mode"}) if transport == "stdio" else (_COMMON_FIELDS - {"event_mode"}) | {"url"}
    _require_fields(raw, allowed, required, f"{transport} app")
    event_mode_value = _optional_text(raw, "event_mode") or "disabled"
    if event_mode_value not in _EVENT_MODES:
        raise ValueError("app.event_mode 不受支持")
    common = {
        "package": text(raw, "package"),
        "enabled": boolean(raw, "enabled"),
        "transport": transport,
        "event_mode": cast("McpEventMode", event_mode_value),
        "timeout_seconds": _positive_number(raw, "timeout_seconds"),
    }
    if transport == "stdio":
        return AppConfig(
            **common,
            working_dir=text(raw, "working_dir"),
            command=_text_array(raw, "command"),
            env=_text_array(raw, "env"),
        )
    return AppConfig(
        **common,
        url=text(raw, "url"),
        auth_env=_optional_text(raw, "auth_env"),
    )


def _require_fields(document: TomlTable, allowed: frozenset[str], required: frozenset[str], label: str) -> None:
    names = set(document)
    unexpected = names - allowed
    missing = required - names
    if unexpected or missing:
        raise ValueError(f"{label} 字段不匹配：未知 {sorted(unexpected)}，缺少 {sorted(missing)}")


def _positive_number(document: TomlTable, key: str) -> float:
    value = document.get(key)
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value) or value <= 0:
        raise ValueError(f"配置字段 {key} 必须是有限正数")
    return float(value)


def _text_array(document: TomlTable, key: str) -> tuple[str, ...]:
    value = document.get(key)
    if not isinstance(value, (list, tuple)) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise ValueError(f"配置字段 {key} 必须是文本数组")
    return tuple(value)


def _optional_text(document: TomlTable, key: str) -> str | None:
    if key not in document:
        return None
    return text(document, key)


def _validate_relative_directory(value: str) -> None:
    normalized = value.replace("\\", "/")
    path = PurePosixPath(normalized)
    windows_absolute = (
        len(normalized) >= _WINDOWS_ABSOLUTE_MIN_LENGTH and normalized[0].isalpha() and normalized[1:3] == ":/"
    )
    if not value.strip() or "\x00" in value or path.is_absolute() or windows_absolute or ".." in path.parts:
        raise ValueError("app.working_dir 必须是项目内相对目录")


def _validate_environment_names(values: tuple[str, ...], label: str) -> None:
    if len(values) != len(set(values)) or any(_ENVIRONMENT_NAME.fullmatch(item) is None for item in values):
        raise ValueError(f"{label} 必须只包含不重复的环境变量名")


def _validate_https_url(value: str) -> None:
    parsed = urlsplit(value)
    if (
        parsed.scheme.lower() != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise ValueError("streamable_http app.url 必须是不含凭据或片段的 HTTPS URL")


__all__ = ["APPS_CONFIG", "AppConfig", "AppsConfig", "McpEventMode", "McpTransport", "register"]

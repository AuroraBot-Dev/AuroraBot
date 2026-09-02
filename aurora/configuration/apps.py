"""解析并注册 ``config/apps.toml`` 的 MCP 应用定义。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, cast

from aurora.config import ConfigSpec
from aurora.utils.toml import (
    TomlTable,
    boolean,
    check_environment_name,
    check_https_url,
    check_package_name,
    check_positive_number,
    check_relative_directory,
    check_unique_items,
    load_toml,
    non_empty_text_array,
    optional_text,
    positive_number,
    require_fields,
    strings,
    table_array,
    text,
)

if TYPE_CHECKING:
    from pathlib import Path

type McpTransport = Literal["stdio", "streamable_http"]
type McpEventMode = Literal["disabled", "world_events", "legacy_aurora_event"]

_TRANSPORTS = frozenset({"stdio", "streamable_http"})
_EVENT_MODES = frozenset({"disabled", "world_events", "legacy_aurora_event"})
_COMMON_FIELDS = frozenset({"package", "enabled", "transport", "timeout_seconds", "event_mode"})
_STDIO_FIELDS = _COMMON_FIELDS | {"working_dir", "command", "env"}
_HTTP_FIELDS = _COMMON_FIELDS | {"url", "auth_env"}


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
        check_package_name(self.package, "app.package")
        if self.transport not in _TRANSPORTS:
            raise ValueError("app.transport 必须是 stdio 或 streamable_http")
        if self.event_mode not in _EVENT_MODES:
            raise ValueError("app.event_mode 不受支持")
        check_positive_number(self.timeout_seconds, "timeout_seconds")
        if self.transport == "stdio":
            self._validate_stdio()
        else:
            self._validate_http()

    def _validate_stdio(self) -> None:
        if self.working_dir is None:
            raise ValueError("stdio app 必须声明 working_dir")
        check_relative_directory(self.working_dir, "app.working_dir")
        non_empty_text_array(self.command, "app.command")
        _validate_environment_names(self.env, "app.env")
        if self.url is not None or self.auth_env is not None:
            raise ValueError("stdio app 不得声明 url 或 auth_env")

    def _validate_http(self) -> None:
        if self.working_dir is not None or self.command or self.env:
            raise ValueError("streamable_http app 不得声明 working_dir、command 或 env")
        if self.url is None:
            raise ValueError("streamable_http app 必须声明 HTTPS url")
        check_https_url(self.url, "app.url")
        if self.event_mode == "world_events":
            raise ValueError("streamable_http app 暂不支持 world_events")
        if self.auth_env is not None:
            _validate_environment_names((self.auth_env,), "app.auth_env")


def _parse(path: Path) -> tuple[AppConfig, ...]:
    document = load_toml(path)
    require_fields(document, frozenset({"app"}), frozenset({"app"}), "apps.toml")
    raw_apps = table_array(document, "app")
    apps = tuple(_parse_app(item) for item in raw_apps)
    check_unique_items(tuple(app.package for app in apps), "app.package")
    return apps


def _parse_app(raw: TomlTable) -> AppConfig:
    transport = cast("McpTransport", text(raw, "transport"))
    allowed = _STDIO_FIELDS if transport == "stdio" else _HTTP_FIELDS
    required = (_STDIO_FIELDS - {"event_mode"}) if transport == "stdio" else (_COMMON_FIELDS - {"event_mode"}) | {"url"}
    require_fields(raw, allowed, required, f"{transport} app")
    event_mode_value = optional_text(raw, "event_mode") or "disabled"
    common = {
        "package": text(raw, "package"),
        "enabled": boolean(raw, "enabled"),
        "transport": transport,
        "event_mode": cast("McpEventMode", event_mode_value),
        "timeout_seconds": positive_number(raw, "timeout_seconds"),
    }
    if transport == "stdio":
        return AppConfig(
            **common,
            working_dir=text(raw, "working_dir"),
            command=strings(raw, "command"),
            env=strings(raw, "env"),
        )
    return AppConfig(
        **common,
        url=text(raw, "url"),
        auth_env=optional_text(raw, "auth_env"),
    )


def _validate_environment_names(values: tuple[str, ...], label: str) -> None:
    check_unique_items(values, label)
    for item in values:
        check_environment_name(item, label)


APPS_CONFIG = ConfigSpec[tuple[AppConfig, ...]](
    name="apps",
    path="config/apps.toml",
    parse=_parse,
)

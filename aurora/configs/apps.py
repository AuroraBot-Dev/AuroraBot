"""解析并注册 ``config/apps.toml`` 的 MCP 应用定义。"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from aurora.contracts.config import ConfigSpec
from aurora.utils.toml import (
    boolean,
    check_unique_items,
    load_toml,
    optional_text,
    positive_number,
    require_fields,
    strings,
    table_array,
    text,
)
from src.mcp.config import AppConfig, AppsConfig, McpEventMode, McpTransport

if TYPE_CHECKING:
    from pathlib import Path

    from aurora.utils.toml import TomlTable

_COMMON_FIELDS = frozenset({"package", "enabled", "transport", "timeout_seconds", "event_mode"})
_STDIO_FIELDS = _COMMON_FIELDS | {"working_dir", "command", "env"}
_HTTP_FIELDS = _COMMON_FIELDS | {"url", "auth_env"}


def _parse(path: Path) -> AppsConfig:
    document = load_toml(path)
    require_fields(document, frozenset({"app"}), frozenset({"app"}), "apps.toml")
    raw_apps = table_array(document, "app")
    apps = tuple(_parse_app(item) for item in raw_apps)
    check_unique_items(tuple(app.package for app in apps), "app.package")
    return AppsConfig(apps)


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


APPS_CONFIG = ConfigSpec[AppsConfig](
    name="apps",
    path="config/apps.toml",
    parse=_parse,
)

CONFIG_SPEC = APPS_CONFIG

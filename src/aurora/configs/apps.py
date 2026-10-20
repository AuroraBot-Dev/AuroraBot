"""解析并注册 ``config/apps.toml`` 的 MCP 应用定义。"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from aurora.contracts.config import ConfigSpec
from aurora.utils.toml import (
    boolean,
    load_toml,
    optional_text,
    positive_number,
    require_fields,
    strings,
    table_array,
    text,
)
from aurorabot.mcp.config import AppConfig, AppsConfig, McpEventMode, McpTransport
from aurorabot.utils.validation import check_unique_items

if TYPE_CHECKING:
    from pathlib import Path

    from aurora.utils.toml import TomlTable

_COMMON_FIELDS = frozenset({"package", "enabled", "transport", "timeout_seconds", "event_mode"})
_STDIO_FIELDS = _COMMON_FIELDS | {"working_dir", "command", "env", "scopes"}
_HTTP_FIELDS = _COMMON_FIELDS | {"url", "auth_env", "scopes"}
_OPTIONAL_FIELDS = frozenset({"event_mode", "scopes"})
_STDIO_REQUIRED = _STDIO_FIELDS - _OPTIONAL_FIELDS
_HTTP_REQUIRED = (_COMMON_FIELDS - _OPTIONAL_FIELDS) | {"url"}


def _parse(path: Path) -> AppsConfig:
    document = load_toml(path)
    require_fields(document, frozenset({"app"}), frozenset({"app"}), "apps.toml")
    raw_apps = table_array(document, "app")
    apps = tuple(_parse_app(item) for item in raw_apps)
    check_unique_items(tuple(app.package for app in apps), "app.package")
    return AppsConfig(apps)


def _parse_app(raw: TomlTable) -> AppConfig:
    transport = cast("McpTransport", text(raw, "transport"))
    stdio = transport == "stdio"
    allowed = _STDIO_FIELDS if stdio else _HTTP_FIELDS
    required = _STDIO_REQUIRED if stdio else _HTTP_REQUIRED
    require_fields(raw, allowed, required, f"{transport} app")
    event_mode_value = optional_text(raw, "event_mode") or "disabled"
    common = {
        "package": text(raw, "package"),
        "enabled": boolean(raw, "enabled"),
        "transport": transport,
        "event_mode": cast("McpEventMode", event_mode_value),
        "timeout_seconds": positive_number(raw, "timeout_seconds"),
        "scopes": strings(raw, "scopes") if "scopes" in raw else (),
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


CONFIG_SPEC = ConfigSpec[AppsConfig](
    name="apps",
    path="config/apps.toml",
    parse=_parse,
)

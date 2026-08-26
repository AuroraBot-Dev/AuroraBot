"""解析 ``config/runtime.toml`` 的 root Agent 入口与 Panel 配置。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from aurora.config import ConfigKey
from aurora.utils.toml import TomlTable, boolean, load_toml, positive_integer, strings, table, text

if TYPE_CHECKING:
    from pathlib import Path

    from aurora.config import ConfigCollector

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})
_MAX_PORT = 65535


@dataclass(frozen=True, slots=True)
class PanelConfig:
    enabled: bool
    host: str
    port: int
    frontend_url: str | None
    allowed_origins: tuple[str, ...]
    open_browser: bool
    session_ttl_seconds: int


@dataclass(frozen=True, slots=True)
class RuntimeConfig:
    node_id: str
    agent: str
    console_enabled: bool
    panel: PanelConfig
    profile: str


RUNTIME_CONFIG = ConfigKey[RuntimeConfig]("runtime")


def register(configs: ConfigCollector) -> None:
    configs.register(RUNTIME_CONFIG, "config/runtime.toml", _parse)


def _parse(path: Path) -> RuntimeConfig:
    runtime = table(load_toml(path), "runtime")
    tree = table(runtime, "tree")
    console = table(runtime, "console")
    return RuntimeConfig(
        text(tree, "node_id"),
        text(tree, "agent"),
        boolean(console, "enabled"),
        _parse_panel(table(runtime, "panel")),
        text(runtime, "profile"),
    )


def _parse_panel(panel: TomlTable) -> PanelConfig:
    enabled = boolean(panel, "enabled")
    host = text(panel, "host")
    if host not in _LOOPBACK_HOSTS:
        raise ValueError("runtime.panel.host 必须是 loopback 地址（127.0.0.1、::1 或 localhost）")
    port = positive_integer(panel, "port")
    if port > _MAX_PORT:
        raise ValueError("runtime.panel.port 必须在 1 到 65535 之间")
    origins = strings(panel, "allowed_origins")
    for origin in origins:
        _validate_origin(origin, "runtime.panel.allowed_origins")
    if len(set(origins)) != len(origins):
        raise ValueError("runtime.panel.allowed_origins 不得重复")
    frontend_value = panel.get("frontend_url")
    frontend_url: str | None = None
    if frontend_value is not None:
        if not isinstance(frontend_value, str) or not frontend_value.strip():
            raise ValueError("runtime.panel.frontend_url 必须是非空文本")
        frontend_url = frontend_value.strip()
        _validate_origin(frontend_url, "runtime.panel.frontend_url")
        if frontend_url not in origins:
            raise ValueError("runtime.panel.frontend_url 必须属于 allowed_origins")
    open_browser = boolean(panel, "open_browser")
    if open_browser and frontend_url is None:
        raise ValueError("runtime.panel.open_browser 需要显式 frontend_url")
    return PanelConfig(
        enabled,
        host,
        port,
        frontend_url,
        origins,
        open_browser,
        positive_integer(panel, "session_ttl_seconds"),
    )


def _validate_origin(value: str, field: str) -> None:
    parts = urlsplit(value)
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise ValueError(f"{field} 必须是明确的 http(s) 来源")
    if parts.path not in {"", "/"} or parts.query or parts.fragment:
        raise ValueError(f"{field} 不得包含路径、查询或片段")
    if parts.username or parts.password:
        raise ValueError(f"{field} 不得包含凭据")

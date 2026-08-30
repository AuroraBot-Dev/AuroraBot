"""解析 ``config/runtime.toml`` 的 root Agent 入口与 Panel 配置。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from aurora.config import ConfigKey
from aurora.utils.toml import (
    TomlTable,
    boolean,
    check_http_origin,
    check_loopback_host,
    check_port,
    check_positive_integer,
    check_unique_items,
    load_toml,
    non_empty_text,
    positive_integer,
    strings,
    table,
    text,
)

if TYPE_CHECKING:
    from pathlib import Path

    from aurora.config import ConfigCollector


@dataclass(frozen=True, slots=True)
class PanelConfig:
    enabled: bool
    host: str
    port: int
    frontend_url: str | None
    allowed_origins: tuple[str, ...]
    open_browser: bool
    session_ttl_seconds: int

    def __post_init__(self) -> None:
        check_loopback_host(self.host, "runtime.panel.host")
        check_port(self.port, "runtime.panel.port")
        for origin in self.allowed_origins:
            check_http_origin(origin, "runtime.panel.allowed_origins")
        check_unique_items(self.allowed_origins, "runtime.panel.allowed_origins")
        if self.frontend_url is not None:
            check_http_origin(self.frontend_url, "runtime.panel.frontend_url")
            if self.frontend_url not in self.allowed_origins:
                raise ValueError("runtime.panel.frontend_url 必须属于 allowed_origins")
        if self.open_browser and self.frontend_url is None:
            raise ValueError("runtime.panel.open_browser 需要显式 frontend_url")
        check_positive_integer(self.session_ttl_seconds, "session_ttl_seconds")


@dataclass(frozen=True, slots=True)
class RuntimeConfig:
    node_id: str
    agent: str
    console_enabled: bool
    panel: PanelConfig
    profile: str

    def __post_init__(self) -> None:
        non_empty_text(self.node_id, "node_id")
        non_empty_text(self.agent, "agent")
        non_empty_text(self.profile, "profile")


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
    frontend_url = panel.get("frontend_url")
    return PanelConfig(
        boolean(panel, "enabled"),
        text(panel, "host"),
        positive_integer(panel, "port"),
        str(frontend_url) if frontend_url is not None else None,
        strings(panel, "allowed_origins"),
        boolean(panel, "open_browser"),
        positive_integer(panel, "session_ttl_seconds"),
    )

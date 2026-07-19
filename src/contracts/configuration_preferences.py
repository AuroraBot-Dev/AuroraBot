"""Immutable preference snapshot and strict RFC 0014 TOML validation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.contracts.configuration import (
    ConfigurationError,
    ConfigurationSource,
    _read_toml_snapshot,
    _require_keys,
)


@dataclass(frozen=True, slots=True)
class ConsolePreferenceConfig:
    enabled: bool
    terminal_logs: bool


@dataclass(frozen=True, slots=True)
class DashboardPreferenceConfig:
    enabled: bool
    open_browser: bool


@dataclass(frozen=True, slots=True)
class McpPreferenceConfig:
    enabled: bool
    terminal_logs: bool


@dataclass(frozen=True, slots=True)
class PlatformPreferenceConfig:
    console: ConsolePreferenceConfig
    dashboard: DashboardPreferenceConfig
    mcp: McpPreferenceConfig


@dataclass(frozen=True, slots=True)
class PreferenceConfig:
    source: ConfigurationSource
    platform: PlatformPreferenceConfig


def _table(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ConfigurationError(f"{label} must be a table")
    return value


def _boolean(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise ConfigurationError(f"{label} must be boolean")
    return value


def load_preference(root: Path) -> PreferenceConfig:
    """Load preference.toml as a standalone, auditable configuration snapshot."""
    data, source = _read_toml_snapshot(root.resolve() / "config" / "preference.toml")
    _require_keys(data, {"platform"}, "preference.toml")
    platform = _table(data["platform"], "platform")
    _require_keys(platform, {"console", "dashboard", "mcp"}, "platform")

    console = _table(platform["console"], "platform.console")
    dashboard = _table(platform["dashboard"], "platform.dashboard")
    mcp = _table(platform["mcp"], "platform.mcp")
    _require_keys(console, {"enabled", "terminal_logs"}, "platform.console")
    _require_keys(dashboard, {"enabled", "open_browser"}, "platform.dashboard")
    _require_keys(mcp, {"enabled", "terminal_logs"}, "platform.mcp")

    return PreferenceConfig(
        source=source,
        platform=PlatformPreferenceConfig(
            console=ConsolePreferenceConfig(
                enabled=_boolean(console["enabled"], "platform.console.enabled"),
                terminal_logs=_boolean(console["terminal_logs"], "platform.console.terminal_logs"),
            ),
            dashboard=DashboardPreferenceConfig(
                enabled=_boolean(dashboard["enabled"], "platform.dashboard.enabled"),
                open_browser=_boolean(dashboard["open_browser"], "platform.dashboard.open_browser"),
            ),
            mcp=McpPreferenceConfig(
                enabled=_boolean(mcp["enabled"], "platform.mcp.enabled"),
                terminal_logs=_boolean(mcp["terminal_logs"], "platform.mcp.terminal_logs"),
            ),
        ),
    )

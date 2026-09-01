"""解析 Panel 纯配置为 ops.panel 运行实例，并管理启动提示。"""

from __future__ import annotations

import webbrowser
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from ops.panel import PanelServer, PanelSettings, PanelStore, create_panel_app, print_panel_notice

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from aurora.configuration.platforms import PlatformConfig
    from aurora.configuration.storage import StorageConfig
    from ops.runtime import OpsRuntime


@dataclass(frozen=True, slots=True)
class PanelRuntime:
    settings: PanelSettings
    store: PanelStore
    server: PanelServer


def panel_data_directory(storage: StorageConfig, project_root: Path) -> Path:
    return project_root / storage.resolve("ops")


def build_panel_runtime(
    panel: PlatformConfig,
    ops: OpsRuntime,
    *,
    storage: StorageConfig,
    project_root: Path,
    profile: str,
) -> PanelRuntime | None:
    if not panel.enabled:
        return None
    settings = PanelSettings(
        host=str(panel.settings("host", "127.0.0.1")),
        port=cast("int", panel.settings("port", 8765)),
        allowed_origins=cast("tuple[str, ...]", panel.settings("allowed_origins", ())),
        session_ttl_seconds=cast("int", panel.settings("session_ttl_seconds", 604800)),
        profile=profile,
    )
    store = PanelStore(
        panel_data_directory(storage, project_root),
        session_ttl_seconds=settings.session_ttl_seconds,
    )
    return PanelRuntime(settings, store, PanelServer(create_panel_app(ops, store, settings), settings))


def open_panel_frontend(url: str) -> None:
    webbrowser.open(url)


async def run_panel(
    panel: PlatformConfig,
    ops: OpsRuntime,
    *,
    storage: StorageConfig,
    project_root: Path,
    profile: str,
    notice: Callable[[PanelSettings, PanelStore], None] = print_panel_notice,
    open_frontend: Callable[[str], None] = open_panel_frontend,
) -> PanelRuntime | None:
    runtime = build_panel_runtime(panel, ops, storage=storage, project_root=project_root, profile=profile)
    if runtime is None:
        return None
    await runtime.server.start()
    notice(runtime.settings, runtime.store)
    if bool(panel.settings("open_browser", False)) and panel.settings("frontend_url") is not None:
        open_frontend(str(panel.settings("frontend_url")))
    return runtime


async def close_panel(panel: PanelRuntime | None) -> None:
    if panel is not None:
        await panel.server.close()

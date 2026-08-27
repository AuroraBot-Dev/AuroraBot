"""把 Panel 纯配置解析为 ops.panel 运行实例并管理启动提示。"""

from __future__ import annotations

import webbrowser
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ops.panel import PanelServer, PanelSettings, PanelStore, create_panel_app, print_panel_notice

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from aurora.configuration.runtime import PanelConfig
    from aurora.configuration.storage import StorageConfig
    from ops.runtime import OpsRuntime


@dataclass(frozen=True, slots=True)
class PanelRuntime:
    settings: PanelSettings
    store: PanelStore
    server: PanelServer


def panel_data_directory(storage: StorageConfig, project_root: Path) -> Path:
    return project_root / storage.data_root / storage.ops


def build_panel_runtime(
    panel: PanelConfig,
    ops: OpsRuntime,
    *,
    storage: StorageConfig,
    project_root: Path,
    profile: str,
) -> PanelRuntime | None:
    if not panel.enabled:
        return None
    settings = PanelSettings(
        host=panel.host,
        port=panel.port,
        allowed_origins=panel.allowed_origins,
        session_ttl_seconds=panel.session_ttl_seconds,
        profile=profile,
    )
    store = PanelStore(
        panel_data_directory(storage, project_root),
        session_ttl_seconds=panel.session_ttl_seconds,
    )
    return PanelRuntime(settings, store, PanelServer(create_panel_app(ops, store, settings), settings))


def open_panel_frontend(url: str) -> None:
    webbrowser.open(url)


async def run_panel(
    panel: PanelConfig,
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
    if panel.open_browser and panel.frontend_url is not None:
        open_frontend(panel.frontend_url)
    return runtime


async def close_panel(panel: PanelRuntime | None) -> None:
    if panel is not None:
        await panel.server.close()

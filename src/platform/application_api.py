from __future__ import annotations

from typing import TYPE_CHECKING

from src.config import Config
from src.utils.log_utils import get_logger

if TYPE_CHECKING:
    from pathlib import Path

    from src.platform.application_host import ApplicationHost
    from src.platform.contracts import AppEvent, CommandSpec
    from src.platform.manifest import Manifest


class PlatformAPI:
    def __init__(self, manifest: "Manifest", host: "ApplicationHost") -> None:
        self._manifest = manifest
        self._host = host
        self._logger = get_logger(f"AppAPI:{manifest.package}")

    # 推送APP事件到内核
    def emit_event(self, event: AppEvent) -> None:
        self._host.emit_event(event)

    def post_intention(self, event: AppEvent) -> None:
        # 兼容旧命名: 应用对内核上报的是事件, 而不是旧 PAA 的 TodoItem.
        self.emit_event(event)

    # 注册命令
    def register_command(self, spec: CommandSpec) -> None:
        self._host.register_command(spec)

    def log(self, level: str, message: str) -> None:
        log_method = getattr(self._logger, level, self._logger.info)
        log_method(message)

    @property
    def package(self) -> str:
        return self._manifest.package

    @property
    def data_dir(self) -> Path:
        path = Config.APP_DATA_DIR / self._manifest.package.replace(".", "_")
        path.mkdir(parents=True, exist_ok=True)
        return path

from __future__ import annotations
from collections import deque
from collections.abc import Iterable
import inspect
from typing import Any

from src.platform.application_api import PlatformAPI
from src.platform.application_protocol import ApplicationProtocol
from src.platform.contracts import AppEvent, CommandSpec
from src.platform.manifest import CommandDecl, Manifest
from src.utils.log_utils import get_logger

logger = get_logger("ApplicationHost")


class ApplicationHost:
    def __init__(self) -> None:
        self._apps: dict[str, ApplicationProtocol] = {}
        self._manifests: dict[str, Manifest] = {}
        self._commands: dict[str, CommandSpec] = {}
        self._events: deque[AppEvent] = deque()

    async def register(self, app: ApplicationProtocol) -> None:
        manifest = Manifest.load(app.manifest_path())
        if not manifest.package:
            raise ValueError(f"需要在manifest中指定package字段: {app.manifest_path()}")
        if manifest.package in self._apps:
            logger.warning(f"应用 {manifest.package} 已注册")
            return
        for command_decl in manifest.commands:
            handler = getattr(app, command_decl.name, None)
            if handler is None:
                raise AttributeError(
                    f"应用 {manifest.package} 缺少 {command_decl.name} 命令实现"
                )
            self.register_command(
                CommandSpec(
                    name=f"{manifest.package}.{command_decl.name}",
                    description=command_decl.description.strip(),
                    parameters_schema=command_decl.to_parameters_schema(),
                    returns_schema=command_decl.to_returns_schema(),
                    handler=handler,
                )
            )
        bind = getattr(app, "_bind", None)
        if callable(bind):
            result = bind(PlatformAPI(manifest, self))
            if inspect.isawaitable(result):
                await result
        await _maybe_await(app.on_start())
        self._apps[manifest.package] = app
        self._manifests[manifest.package] = manifest
        logger.info(f"已注册应用: {manifest.package}")

    def register_command(self, spec: CommandSpec) -> None:
        if not spec.name.strip():
            raise ValueError("命令名称不能为空")
        self._commands[spec.name] = spec

    def emit_event(self, event: AppEvent) -> None:
        self._events.append(event)
        logger.info(f"已推送应用事件: {event.type}")

    # 从事件队列中提取事件
    def drain_events(self, limit: int | None = None) -> list[AppEvent]:
        drained: list[AppEvent] = []
        remaining = limit if limit is not None and limit >= 0 else None
        while self._events and (remaining is None or remaining > 0):
            drained.append(self._events.popleft())
            if remaining is not None:
                remaining -= 1
        return drained

    def peek_events(self) -> list[AppEvent]:
        return list(self._events)

    def list_apps(self) -> list[str]:
        return list(self._apps.keys())

    def list_commands(self) -> list[str]:
        return sorted(self._commands.keys())

    def list_command_specs(self) -> list[CommandSpec]:
        return [self._commands[name] for name in sorted(self._commands.keys())]

    def get_app(self, package: str) -> ApplicationProtocol | None:
        return self._apps.get(package)

    def iter_manifests(self) -> Iterable[Manifest]:
        return self._manifests.values()

    # 执行命令
    async def invoke_command(self, command_name: str, **kwargs: Any) -> Any:
        spec = self._commands.get(command_name)
        if spec is None:
            raise KeyError(f"Unknown command: {command_name}")
        logger.info(f"执行命令: {command_name}")
        return await _maybe_await(spec.handler(**kwargs))

    async def tick(self) -> None:
        # 执行所有应用的 on_tick 方法
        for package, app in self._apps.items():
            try:
                await _maybe_await(app.on_tick())
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"应用 {package} 执行 on_tick 失败: {exc}")

    async def stop_all(self) -> None:
        for package, app in reversed(list(self._apps.items())):
            try:
                await _maybe_await(app.on_stop())
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"应用 {package} 执行 on_stop 失败: {exc}")
        self._apps.clear()
        self._manifests.clear()
        self._commands.clear()
        self._events.clear()
        logger.info("已注销所有应用")


async def _maybe_await(result: Any) -> Any:
    if inspect.isawaitable(result):
        return await result
    return result


app_host = ApplicationHost()

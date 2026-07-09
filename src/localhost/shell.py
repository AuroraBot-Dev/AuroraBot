"""控制台命令解析与事件循环 —— 内置交互式 Shell。

用法::

    from src.localhost.shell import handle_control_command, run_console_control_loop

    async def dispatch(raw: str) -> None:
        await handle_control_command(raw, runtime=rt, lock=lk)

    await run_console_control_loop(dispatch, idle_delay=0.5)

作者: [Churk-Ben](https://github.com/Churk-Ben)
"""

from __future__ import annotations

import asyncio
import shlex
import sys
import threading
from typing import TYPE_CHECKING

from src.localhost.registry import (
    SAY_COMMANDS,
    ParsedConsoleCommand,
    _console_commands,
)
from src.localhost.reloader import HotReloadError
from src.utils.log_utils import get_logger

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from src.runtime import RuntimeState

logger = get_logger("Localhost")


def _runtime_after_command_error(
    exc: Exception,
    *,
    command_name: str,
    runtime: RuntimeState,
) -> RuntimeState | None:
    if isinstance(exc, HotReloadError) or exc.__class__.__name__ == "HotReloadError":
        logger.exception("热重载失败")
        return getattr(exc, "runtime", runtime)

    logger.exception(f"指令执行失败: {command_name}")
    return runtime


def _parse_control_command(raw: str) -> ParsedConsoleCommand | None:
    command_line = raw.strip()
    if not command_line:
        return None

    try:
        tokens = shlex.split(command_line)
    except ValueError:
        logger.warning(f"控制台命令解析失败: {command_line}")
        return None

    if not tokens:
        return None

    name = tokens[0]
    for spec in _console_commands():
        if name in spec.names:
            raw_args = command_line.split(maxsplit=1)[1] if len(tokens) > 1 else ""
            return ParsedConsoleCommand(
                raw=command_line,
                name=name,
                args=tuple(tokens[1:]),
                raw_args=raw_args,
                spec=spec,
            )
    return None


async def handle_control_command(
    raw: str,
    *,
    runtime: RuntimeState | None,
    lock: asyncio.Lock,
) -> RuntimeState | None:
    parsed = _parse_control_command(raw)
    if parsed is None:
        text = raw.strip()
        if not text:
            return runtime
        say_spec = next(spec for spec in _console_commands() if spec.names == SAY_COMMANDS)
        parsed = ParsedConsoleCommand(
            raw=raw,
            name=SAY_COMMANDS[0],
            args=(text,),
            raw_args=text,
            spec=say_spec,
        )
    if runtime is None:
        logger.warning("控制命令已忽略: runtime 尚未初始化")
        return runtime
    if lock.locked():
        logger.debug("已有控制任务在执行，忽略重复指令")
        return runtime

    logger.debug("执行指令: %s", parsed.name)
    async with lock:
        try:
            return await parsed.spec.handler(runtime, parsed)
        except Exception as exc:  # noqa: BLE001 - console command boundary must keep runtime alive.
            return _runtime_after_command_error(exc, command_name=parsed.name, runtime=runtime)


async def run_console_control_loop(
    dispatch_command: Callable[[str], Awaitable[None]],
    *,
    readline: Callable[[], str] | None = None,
    idle_delay: float = 0.5,
) -> None:
    read_line = readline or sys.stdin.readline
    loop = asyncio.get_running_loop()
    input_queue: asyncio.Queue[str] = asyncio.Queue()
    stop_event = threading.Event()

    def _reader() -> None:
        while not stop_event.is_set():
            try:
                line = read_line()
            except Exception:
                logger.exception("控制台输入读取失败")
                break

            if line == "":
                if stop_event.wait(idle_delay):
                    break
                continue

            try:
                loop.call_soon_threadsafe(input_queue.put_nowait, line)
            except RuntimeError:
                break

    reader_thread = threading.Thread(
        target=_reader,
        name="console-control-reader",
        daemon=True,
    )
    reader_thread.start()
    logger.info("控制台命令监听已启动，使用 `/help` 查看支持的命令")
    try:
        while True:
            line = await input_queue.get()
            command = line.strip()
            if not command:
                continue

            await dispatch_command(command)
    except asyncio.CancelledError:
        stop_event.set()
        logger.info("控制台命令监听已停止")
        raise

"""本地 Console 交互 Shell 与输出渲染。

位于热路径之外：输入经控制端口路由，输出通过只读查询端口按游标拉取并渲染，
不拥有任何 Tool 能力。
"""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from prompt_toolkit import PromptSession
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.patch_stdout import patch_stdout
from prompt_toolkit.shortcuts import clear as clear_terminal

from src.contracts import (
    CommandControl,
    InputOrigin,
    RuntimeInput,
)
from src.utils import get_logger

logger = get_logger("aurora.console")

_RENDER_POLL_SECONDS = 0.2
"""输出流轮询间隔。"""


if TYPE_CHECKING:
    from collections.abc import Callable

    from prompt_toolkit.input import Input
    from prompt_toolkit.output import Output

    from src.contracts.ports import ConsoleControlPort, RuntimeQueryPort


@dataclass(frozen=True, slots=True)
class _ReadResult:
    """单次用户输入的读取结果。"""

    text: str | None
    """用户输入的文本，为 None 表示输入流已关闭。"""
    closed: bool = False
    """输入流是否已关闭（EOF / Ctrl+C / Ctrl+D）。"""


class _PromptReader:
    """基于 prompt_toolkit 的提示行读取器。"""

    def __init__(self, *, input_stream: Input | None = None, output_stream: Output | None = None) -> None:
        """初始化提示会话，支持历史搜索。

        Args:
            input_stream: 可选的输入流（用于测试注入）。
            output_stream: 可选的输出流（用于测试注入）。
        """
        self.session: PromptSession[str] = PromptSession(
            history=InMemoryHistory(),
            enable_history_search=True,
            input=input_stream,
            output=output_stream,
        )

    async def read(self) -> str:
        """阻塞等待用户输入一行文本。"""
        return await self.session.prompt_async("You> ")


async def run_console(
    control: ConsoleControlPort,
    query: RuntimeQueryPort,
    *,
    stop_event: asyncio.Event | None = None,
    readline: Callable[[str], str] | None = None,
    output: Callable[[str], None] = print,
    poll_seconds: float = _RENDER_POLL_SECONDS,
) -> None:
    """运行本地 Console 交互主循环，路由输入并渲染 Bot 输出。

    主循环负责：读取用户输入、通过控制端口路由、按游标拉取输出流并打印、
    处理清屏和关机等控制指令。

    Args:
        control: Console 控制端口，用于路由输入和控制命令。
        query: 只读输出流查询端口，用于渲染 Bot 输出。
        stop_event: 外部停止信号。
        readline: 可注入的读取函数（测试用），为 None 时使用 prompt_toolkit。
        output: 输出回调函数。
        poll_seconds: 输出流轮询间隔。
    """
    stop = stop_event or asyncio.Event()
    output("AuroraBot local console; 输入 /help 查看命令。")
    prompt_reader = _PromptReader() if readline is None else None
    display = asyncio.create_task(_display_messages(query, output, poll_seconds), name="aurora-console-output")
    logger.info("local console started")
    try:
        terminal_context = patch_stdout(raw=True) if prompt_reader is not None else contextlib.nullcontext()
        with terminal_context:
            while not stop.is_set():
                result, should_stop = await _read_input_or_stop(prompt_reader, readline, stop)
                if should_stop:
                    return
                if result.closed:
                    output("")
                    control.request_shutdown()
                    return
                raw = (result.text or "").strip()
                if not raw:
                    continue
                external_event_id = str(uuid4())
                # 将用户输入路由到 ops 的控制端口
                routed = await control.route_input(
                    RuntimeInput(
                        text=raw,
                        origin=InputOrigin.CONSOLE,
                        session_id="local:console",
                        source_app="local.console",
                        source_instance="default",
                        idempotency_key=external_event_id,
                        data={"channel": "local_console"},
                    )
                )
                if routed.control is CommandControl.CLEAR_CONSOLE:
                    _clear_console(prompt_reader, output)
                    continue
                if routed.text is not None:
                    output(routed.text)
                if routed.control is CommandControl.SHUTDOWN_PROCESS:
                    control.request_shutdown()
                    return
    finally:
        await _cancel_tasks(display)
        logger.info("local console stopped")


async def _read_input_or_stop(
    prompt_reader: _PromptReader | None,
    readline: Callable[[str], str] | None,
    stop: asyncio.Event,
) -> tuple[_ReadResult, bool]:
    """等待用户输入或停止信号，返回 (输入结果, 是否因停止而退出)。"""
    read_task = asyncio.create_task(_read_input(prompt_reader, readline), name="aurora-console-read")
    stop_task = asyncio.create_task(stop.wait(), name="aurora-console-stop")
    # 等待第一个完成的任务（用户输入或停止信号）
    done, pending = await asyncio.wait({read_task, stop_task}, return_when=asyncio.FIRST_COMPLETED)
    for task in pending:
        task.cancel()
    if read_task in pending:
        await asyncio.gather(read_task, return_exceptions=True)
    if stop_task in pending:
        await asyncio.gather(stop_task, return_exceptions=True)
    if stop_task in done and stop.is_set():
        return _ReadResult(None, closed=True), True
    return read_task.result(), False


async def _read_input(
    prompt_reader: _PromptReader | None,
    readline: Callable[[str], str] | None,
) -> _ReadResult:
    """从 prompt_toolkit 或可注入函数读取一行用户输入。

    捕获 EOF / Ctrl+C 并返回已关闭的结果。
    """
    try:
        if prompt_reader is not None:
            return _ReadResult(await prompt_reader.read())
        assert readline is not None
        return _ReadResult(await asyncio.to_thread(readline, "You> "))
    except (EOFError, KeyboardInterrupt, StopIteration):
        return _ReadResult(None, closed=True)


def _clear_console(prompt_reader: _PromptReader | None, output: Callable[[str], None]) -> None:
    """清空终端屏幕。

    prompt_toolkit 环境下使用其内置清屏；非交互环境使用 ANSI 转义序列。
    """
    if prompt_reader is not None:
        clear_terminal()
    else:
        output("\033[2J\033[H")


async def _display_messages(
    query: RuntimeQueryPort,
    output: Callable[[str], None],
    poll_seconds: float,
) -> None:
    """按游标轮询输出流并渲染 Bot 的用户可见文本。"""
    cursor = 0
    while True:
        page = query.output_stream(cursor)
        for item in page.items:
            if item.text:
                prefix = "Bot! " if item.kind == "error" else "Bot> "
                output(f"{prefix}{item.text}")
        cursor = page.next_cursor
        await asyncio.sleep(poll_seconds)


async def _cancel_tasks(*tasks: asyncio.Task[Any] | None) -> None:
    """批量取消多个异步任务并等待完成。"""
    active = [task for task in tasks if task is not None]
    for task in active:
        task.cancel()
    await asyncio.gather(*active, return_exceptions=True)

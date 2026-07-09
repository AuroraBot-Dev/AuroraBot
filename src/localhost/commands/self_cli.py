"""Pool A CLI 命令：/stream, /state, /memories —— 查看她的自我之流。

作者: [Churk-Ben](https://github.com/Churk-Ben)
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING

from src.nodes.self_stream import SelfStream
from src.utils.log_utils import get_logger

if TYPE_CHECKING:
    from src.localhost.registry import ParsedConsoleCommand
    from src.runtime import RuntimeState

logger = get_logger("SelfCLI")

_stream = SelfStream()


async def _handle_stream_command(
    runtime: RuntimeState,
    parsed: ParsedConsoleCommand,
) -> RuntimeState:
    """查看她最近的自我之流。"""
    n = 30
    if parsed.args:
        with contextlib.suppress(ValueError):
            n = int(parsed.args[0])

    content = _stream.read_recent(n)
    logger.info(content)
    return runtime


async def _handle_state_command(
    runtime: RuntimeState,
    _parsed: ParsedConsoleCommand,
) -> RuntimeState:
    """查看她当前的自我状态。"""
    content = _stream.read_state()
    logger.info(content)
    return runtime


async def _handle_memories_command(
    runtime: RuntimeState,
    parsed: ParsedConsoleCommand,
) -> RuntimeState:
    """查看她的持久记忆。"""
    memories = _stream.list_memories()

    if not memories:
        logger.info("（暂无持久记忆）")
        return runtime

    if parsed.args:
        name = parsed.args[0]
        content = _stream.read_memory(name)
        if content:
            logger.info(content)
        else:
            logger.info(f"未找到记忆: {name}")
    else:
        for name in memories:
            content = _stream.read_memory(name)
            preview = (content or "")[:80].replace("\n", " ")
            logger.info(f"  {name}: {preview}...")
    return runtime

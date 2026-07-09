"""控制台 ``/memtest`` 命令——记忆系统交互测试。

用法::

    /memtest query <text>      检索记忆上下文
    /memtest record <text>     记录一条用户交互
    /memtest context           查看当前记忆上下文

作者: [Churk-Ben](https://github.com/Churk-Ben)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.localhost.utils import _ConsoleArgumentParser
from src.memory import MemoryContext, memory_manager
from src.utils.log_utils import get_logger

if TYPE_CHECKING:
    from src.localhost.registry import ParsedConsoleCommand
    from src.runtime import RuntimeState

logger = get_logger("Localhost")


def _build_memtest_parser() -> _ConsoleArgumentParser:
    parser = _ConsoleArgumentParser(add_help=False, prog="/memtest")
    parser.add_argument("subcommand", nargs="?", default="help")
    parser.add_argument("args", nargs="*", default=[])
    return parser


async def _handle_memtest_command(  # noqa: PLR0911
    runtime: RuntimeState,
    parsed: ParsedConsoleCommand,
) -> RuntimeState:
    parser = _build_memtest_parser()
    try:
        args = parser.parse_args(list(parsed.args))
    except ValueError as exc:
        logger.warning(f"命令 {parsed.name} 参数错误: {exc}")
        return runtime

    sub = (args.subcommand or "help").strip().lower()
    raw_args = " ".join(args.args) if args.args else ""

    if sub == "help":
        logger.info(
            "\n  /memtest query <text>        检索记忆上下文\n"
            "  /memtest record <text>       记录一条用户交互\n"
            "  /memtest context [--user-id ID]  查看当前记忆上下文\n"
        )
        return runtime

    if sub == "context":
        user_id = "localhost"
        ctx: MemoryContext = memory_manager.retrieve_context(current_query="__context_snapshot__", user_id=user_id)
        prompt_text = ctx.to_prompt_text() if ctx else "(空)"
        logger.debug("\n--- 记忆上下文 (user=%s) ---\n%s", user_id, prompt_text)
        return runtime

    if sub == "query":
        if not raw_args:
            logger.warning("query 需要提供查询文本")
            return runtime
        user_id = "localhost"
        ctx = memory_manager.retrieve_context(current_query=raw_args, user_id=user_id)
        prompt_text = ctx.to_prompt_text() if ctx else "(无匹配记忆)"
        logger.info(f"\n--- 记忆检索结果 (query={raw_args}) ---\n{prompt_text}")
        return runtime

    if sub == "record":
        if not raw_args:
            logger.warning("record 需要提供记录文本")
            return runtime
        memory_manager.process_interaction(content=raw_args, role="user", user_id="localhost")
        logger.info(f"已记录交互: {raw_args}")
        return runtime

    logger.warning(f"未知子命令: {sub}，使用 /memtest help 查看用法")
    return runtime

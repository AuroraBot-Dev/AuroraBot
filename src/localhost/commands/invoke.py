"""控制台 ``/invoke`` 命令——调用 MCP Tool。"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from src.localhost.utils import _ConsoleArgumentParser
from src.utils.json_utils import json_ready, parse_json_or_yaml_object
from src.utils.log_utils import get_logger

if TYPE_CHECKING:
    from src.localhost.registry import ParsedConsoleCommand
    from src.runtime import RuntimeState

logger = get_logger("Localhost")


def _build_invoke_parser() -> _ConsoleArgumentParser:
    parser = _ConsoleArgumentParser(add_help=False, prog="/invoke")
    parser.add_argument("tool_name")
    parser.add_argument("--payload", default="")
    return parser


async def _handle_invoke_command(
    runtime: RuntimeState,
    parsed: ParsedConsoleCommand,
) -> RuntimeState:
    parser = _build_invoke_parser()
    try:
        args = parser.parse_args(list(parsed.args))
    except ValueError as exc:
        logger.warning(f"命令 {parsed.name} 参数错误: {exc}")
        return runtime

    arguments = parse_json_or_yaml_object(args.payload)
    if not isinstance(arguments, dict):
        arguments = {}

    try:
        result = await runtime.client_manager.call_tool(args.tool_name, arguments)
        logger.debug(
            "工具调用结果 %s:\n%s",
            args.tool_name,
            json.dumps(
                {"result": json_ready(result)},
                ensure_ascii=False,
                indent=2,
            ),
        )
    except Exception:
        logger.exception("工具调用失败 %s", args.tool_name)

    return runtime

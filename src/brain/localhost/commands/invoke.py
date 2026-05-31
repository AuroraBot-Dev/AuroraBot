from __future__ import annotations

import json
from typing import TYPE_CHECKING

from src.brain.localhost.utils import _ConsoleArgumentParser
from src.utils.json_utils import json_ready, parse_json_or_yaml_object
from src.utils.log_utils import get_logger

if TYPE_CHECKING:
    from src.brain.localhost.registry import ParsedConsoleCommand
    from src.brain.runtime import RuntimeState

logger = get_logger("Localhost")


def _build_invoke_parser() -> _ConsoleArgumentParser:
    parser = _ConsoleArgumentParser(add_help=False, prog="/invoke")
    parser.add_argument("command_name")
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

    payload = parse_json_or_yaml_object(args.payload)
    result = await runtime.host.invoke_command(args.command_name, **payload)
    logger.debug(
        "命令执行结果 %s:\n%s",
        args.command_name,
        json.dumps(
            {"result": json_ready(result)},
            ensure_ascii=False,
            indent=2,
        ),
    )
    return runtime

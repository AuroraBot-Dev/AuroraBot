"""Console /event command — submit a typed immutable cognitive event."""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.kernel.models import CognitiveEvent
from src.localhost.utils import _ConsoleArgumentParser
from src.utils.json_utils import parse_json_or_yaml_object
from src.utils.log_utils import get_logger

if TYPE_CHECKING:
    from src.localhost.registry import ParsedConsoleCommand
    from src.runtime import RuntimeState

logger = get_logger("Localhost")


def _build_event_parser() -> _ConsoleArgumentParser:
    parser = _ConsoleArgumentParser(add_help=False, prog="/event")
    parser.add_argument("event_type")
    parser.add_argument("--source", default="manual.console")
    parser.add_argument("--session", dest="session_id", default="")
    parser.add_argument("--summary", default="")
    parser.add_argument("--payload", default="")
    return parser


async def _handle_event_command(runtime: RuntimeState, parsed: ParsedConsoleCommand) -> RuntimeState:
    try:
        args = _build_event_parser().parse_args(list(parsed.args))
    except ValueError as error:
        logger.warning("命令 %s 参数错误: %s", parsed.name, error)
        return runtime
    if runtime.circuit is None:
        logger.warning("认知运行时尚未启动")
        return runtime
    data = parse_json_or_yaml_object(args.payload)
    await runtime.circuit.submit(
        CognitiveEvent.create(
            "input.external",
            {"kind": args.event_type, "summary": args.summary or str(data.get("text", "")), "data": data},
            source=args.source,
            session_id=args.session_id or "local:console",
            tags={"transport": "console", "original_type": args.event_type},
        )
    )
    logger.info("已写入认知 inbox: %s", args.event_type)
    return runtime

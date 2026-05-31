from __future__ import annotations

import json
from typing import TYPE_CHECKING

from src.brain.localhost.utils import _ConsoleArgumentParser
from src.utils.json_utils import parse_json_or_yaml_object
from src.utils.log_utils import get_logger

if TYPE_CHECKING:
    from src.brain.localhost.registry import ParsedConsoleCommand
    from src.brain.runtime import RuntimeState

logger = get_logger("Localhost")


def _build_event_parser() -> _ConsoleArgumentParser:
    parser = _ConsoleArgumentParser(add_help=False, prog="/event")
    parser.add_argument("event_type")
    parser.add_argument("--source", default="manual.console")
    parser.add_argument("--session", dest="session_id", default="")
    parser.add_argument("--summary", default="")
    parser.add_argument("--payload", default="")
    return parser


async def _handle_event_command(
    runtime: RuntimeState,
    parsed: ParsedConsoleCommand,
) -> RuntimeState:
    from src.platform.contracts import AppEvent

    parser = _build_event_parser()
    try:
        args = parser.parse_args(list(parsed.args))
    except ValueError as exc:
        logger.warning(f"命令 {parsed.name} 参数错误: {exc}")
        return runtime

    payload = parse_json_or_yaml_object(args.payload)
    runtime.host.emit_event(
        AppEvent(
            source=args.source,
            type=args.event_type,
            session_id=args.session_id,
            summary=args.summary or str(payload.get("text", "")),
            payload=payload,
        )
    )
    logger.debug(
        "已注入事件:\n%s",
        json.dumps(
            {
                "type": args.event_type,
                "source": args.source,
                "session": args.session_id,
            },
            ensure_ascii=False,
            indent=2,
        ),
    )
    return runtime

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from src.brain.localhost.registry import ParsedConsoleCommand, _console_commands
from src.brain.localhost.reloader import reload_brain, stop_process
from src.brain.localhost.utils import _ConsoleArgumentParser
from src.utils.log_utils import get_logger

if TYPE_CHECKING:
    from src.brain.runtime import RuntimeState

logger = get_logger("Localhost")


async def _handle_help_command(
    runtime: RuntimeState,
    _parsed: ParsedConsoleCommand,
) -> RuntimeState:
    specs = list(_console_commands())
    usage_width = max((len(spec.usage) for spec in specs), default=0)
    gap = 2
    all_commands = "\n"
    for spec in specs:
        all_commands += f"{spec.usage.ljust(usage_width)}{' ' * gap}{spec.description}\n"
    logger.debug(all_commands)
    return runtime


async def _handle_reload_command(
    runtime: RuntimeState,
    _parsed: ParsedConsoleCommand,
) -> RuntimeState:
    return await reload_brain(runtime=runtime)


async def _handle_stop_command(
    runtime: RuntimeState,
    _parsed: ParsedConsoleCommand,
) -> None:
    await stop_process(runtime=runtime)


def _build_events_parser() -> _ConsoleArgumentParser:
    parser = _ConsoleArgumentParser(add_help=False, prog="/events")
    parser.add_argument("--drain", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    return parser


async def _handle_events_command(
    runtime: RuntimeState,
    parsed: ParsedConsoleCommand,
) -> RuntimeState:
    parser = _build_events_parser()
    try:
        args = parser.parse_args(list(parsed.args))
    except ValueError as exc:
        logger.warning(f"命令 {parsed.name} 参数错误: {exc}")
        return runtime

    events = (
        runtime.host.drain_events(limit=args.limit)
        if args.drain
        else (runtime.host.peek_events()[: args.limit] if args.limit is not None else runtime.host.peek_events())
    )
    logger.debug(
        "当前事件队列:\n%s",
        json.dumps(
            {"events": [event.to_dict() for event in events]},
            ensure_ascii=False,
            indent=2,
        ),
    )
    return runtime


def _build_commands_parser() -> _ConsoleArgumentParser:
    parser = _ConsoleArgumentParser(add_help=False, prog="/commands")
    parser.add_argument("--detail")
    return parser


async def _handle_commands_command(
    runtime: RuntimeState,
    parsed: ParsedConsoleCommand,
) -> RuntimeState:
    parser = _build_commands_parser()
    try:
        args = parser.parse_args(list(parsed.args))
    except ValueError as exc:
        logger.warning(f"命令 {parsed.name} 参数错误: {exc}")
        return runtime

    if not args.detail:
        payload = {"commands": runtime.host.list_commands()}
    else:
        specs = runtime.host.list_command_specs()
        if args.detail == "all":
            payload = {
                "commands": [
                    {
                        "name": spec.name,
                        "description": spec.description,
                        "parameters_schema": spec.parameters_schema,
                        "returns_schema": spec.returns_schema,
                    }
                    for spec in specs
                ]
            }
        else:
            target = next((spec for spec in specs if spec.name == args.detail), None)
            if target is None:
                logger.warning(f"命令 {parsed.name} 未找到: {args.detail}")
                return runtime
            payload = {
                "command": {
                    "name": target.name,
                    "description": target.description,
                    "parameters_schema": target.parameters_schema,
                    "returns_schema": target.returns_schema,
                }
            }
    logger.debug(
        "可用命令:\n%s",
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
        ),
    )
    return runtime


async def _handle_apps_command(
    runtime: RuntimeState,
    _parsed: ParsedConsoleCommand,
) -> RuntimeState:
    logger.debug(
        "已加载应用:\n%s",
        json.dumps(
            {"apps": runtime.host.list_apps()},
            ensure_ascii=False,
            indent=2,
        ),
    )
    return runtime

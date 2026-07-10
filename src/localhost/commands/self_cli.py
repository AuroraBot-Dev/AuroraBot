"""Console views over immutable context frames and rhythm events."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from src.utils.log_utils import get_logger

if TYPE_CHECKING:
    from src.localhost.registry import ParsedConsoleCommand
    from src.runtime import RuntimeState

logger = get_logger("SelfCLI")


async def _handle_stream_command(runtime: RuntimeState, _parsed: ParsedConsoleCommand) -> RuntimeState:
    if runtime.circuit is None:
        return runtime
    logger.info(json.dumps(runtime.circuit.snapshot(), ensure_ascii=False, indent=2))
    return runtime


async def _handle_state_command(runtime: RuntimeState, _parsed: ParsedConsoleCommand) -> RuntimeState:
    if runtime.circuit is None:
        return runtime
    logger.info(json.dumps(runtime.circuit.snapshot(), ensure_ascii=False, indent=2))
    return runtime


async def _handle_memories_command(runtime: RuntimeState, parsed: ParsedConsoleCommand) -> RuntimeState:
    if runtime.circuit is None:
        return runtime
    session_id = parsed.args[0] if parsed.args else "local:console"
    logger.info(json.dumps(runtime.circuit.latest_context(session_id), ensure_ascii=False, indent=2))
    return runtime

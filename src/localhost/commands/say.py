"""Console /say command — submit an immutable external cognitive event."""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.kernel.models import CognitiveEvent
from src.utils.log_utils import get_logger

if TYPE_CHECKING:
    from src.localhost.registry import ParsedConsoleCommand
    from src.runtime import RuntimeState

logger = get_logger("Localhost")


async def _handle_say_command(runtime: RuntimeState, parsed: ParsedConsoleCommand) -> RuntimeState:
    message = " ".join(parsed.args).strip()
    if not message:
        logger.warning("控制台命令 %s 需要提供消息文本", parsed.name)
        return runtime
    if runtime.circuit is None:
        logger.warning("认知运行时尚未启动")
        return runtime
    await runtime.circuit.submit(
        CognitiveEvent.create(
            "input.external",
            {"summary": message, "text": message, "kind": "console.message"},
            source="console",
            session_id="local:console",
            tags={"transport": "console"},
        )
    )
    logger.info("已写入认知 inbox")
    return runtime

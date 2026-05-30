from __future__ import annotations

from typing import TYPE_CHECKING

from src.platform.contracts import AppEvent
from src.utils.log_utils import get_logger

if TYPE_CHECKING:
    from src.brain.localhost.registry import ParsedConsoleCommand
    from src.brain.runtime import RuntimeState

logger = get_logger("Localhost")


async def _handle_say_command(
    runtime: RuntimeState,
    parsed: ParsedConsoleCommand,
) -> RuntimeState:
    message = " ".join(parsed.args).strip()
    if not message:
        logger.warning(f"控制台命令 {parsed.name} 需要提供消息文本")
        return runtime

    session_id = "private:localhost"
    runtime.host.emit_event(
        AppEvent(
            source="manual.console",
            type="message.received",
            session_id=session_id,
            summary=message,
            payload={
                "session_id": session_id,
                "text": message,
                "user_id": "localhost",
                "is_group": False,
                "group_id": None,
                "bot_id": "console",
            },
        )
    )
    logger.debug("已注入消息: %s", message)
    return runtime

"""Console shorthand for a local ``message.received`` AMP event."""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.contracts.amp import new_amp

if TYPE_CHECKING:
    from src.localhost.runtime import AuroraRuntime


async def say_command(runtime: AuroraRuntime, arguments: tuple[str, ...]) -> str:
    """Deliver a message without bypassing AMP ingress or Kernel records."""
    message = " ".join(arguments).strip()
    if not message:
        return "用法: /say <message>"
    amp = new_amp(
        event_type="message.received",
        session_id="local:console",
        summary=message,
        data={"text": message, "reply_capability": "org.aurora.console.send_message"},
        source_app="localhost.console",
        source_instance="default",
    )
    return f"已投递消息 AMP: {await runtime.submit_amp(amp.to_dict())}"

"""Console Platform executor for terminal text effects."""

from __future__ import annotations

import asyncio

from src.contracts.agent import CapabilityDescriptor
from src.localhost.ports import EffectExecutionRequest, EffectOutcome

CONSOLE_SEND_CAPABILITY = "org.aurora.console.send_message"
CONSOLE_SEND_DESCRIPTOR = CapabilityDescriptor(
    id=CONSOLE_SEND_CAPABILITY,
    description="Send one text reply to the active Console session.",
    parameters_schema={
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
        "additionalProperties": False,
    },
    result_mode="terminal",
)


class ConsolePlatform:
    """Own Console output and execute effects without accessing Kernel state."""

    def __init__(self) -> None:
        self._messages: list[str] = []
        self._queue: asyncio.Queue[str] = asyncio.Queue()

    async def execute_effect(self, request: EffectExecutionRequest) -> EffectOutcome:
        if request.capability != CONSOLE_SEND_CAPABILITY:
            return EffectOutcome(
                succeeded=False,
                summary="Console message delivery failed",
                error=f"unsupported Console capability: {request.capability}",
            )
        text = request.parameters.get("text")
        if not isinstance(text, str):
            return EffectOutcome(
                succeeded=False,
                summary="Console message delivery failed",
                error="org.aurora.console.send_message requires string parameters.text",
            )
        self._messages.append(text)
        self._queue.put_nowait(text)
        return EffectOutcome(
            succeeded=True,
            summary="Console message delivered",
            result={"text": text},
        )

    async def next_message(self) -> str:
        message = await self._queue.get()
        self._messages.remove(message)
        return message

    def drain_messages(self) -> tuple[str, ...]:
        messages = tuple(self._messages)
        self._messages.clear()
        while not self._queue.empty():
            self._queue.get_nowait()
        return messages

"""In-process Platform executor for Dashboard reply effects."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from src.contracts.agent import CapabilityDescriptor
from src.localhost.ports import EffectExecutionRequest, EffectOutcome

DASHBOARD_REPLY_CAPABILITY = "org.aurora.dashboard.send_message"
DASHBOARD_REPLY_DESCRIPTOR = CapabilityDescriptor(
    id=DASHBOARD_REPLY_CAPABILITY,
    description="Send one text reply to the Dashboard user who started the current Task.",
    parameters_schema={
        "type": "object",
        "properties": {"text": {"type": "string", "minLength": 1}},
        "required": ["text"],
        "additionalProperties": False,
    },
    result_mode="terminal",
)
ReplySink = Callable[[str, str, str], Awaitable[dict[str, Any]]]


class DashboardPlatform:
    """Deliver one Dashboard publication effect through an injected sink."""

    def __init__(self, sink: ReplySink) -> None:
        self._sink = sink

    async def execute_effect(self, request: EffectExecutionRequest) -> EffectOutcome:
        try:
            if request.capability != DASHBOARD_REPLY_CAPABILITY:
                raise ValueError(f"unsupported Dashboard capability: {request.capability}")
            text = request.parameters.get("text")
            if not isinstance(text, str) or not text:
                raise ValueError("dashboard reply text is invalid")
            message = await self._sink(request.session_id, text, request.request_id)
            return EffectOutcome(
                succeeded=True,
                summary="Dashboard reply delivered",
                result={"message_id": message["message_id"]},
            )
        except Exception as error:  # noqa: BLE001 - external sink failures are structured outcomes.
            return EffectOutcome(
                succeeded=False,
                summary="Dashboard reply failed",
                error=f"{type(error).__name__}: {error}",
            )

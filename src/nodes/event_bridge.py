"""Bridge MCP notifications into immutable cognitive ingress events."""

from __future__ import annotations

import asyncio
from typing import Any

from src.kernel.models import CognitiveEvent
from src.platform.amp import AMPEnvelope, amp_to_file_event, build_event_envelope, parse_amp_envelope
from src.utils.log_utils import get_logger

logger = get_logger("McpEventBridge")


async def run_mcp_event_bridge(client_manager: Any, runtime: Any, stop_event: asyncio.Event) -> None:
    while not stop_event.is_set():
        try:
            server_key, method, params = await asyncio.wait_for(client_manager.notification_queue.get(), timeout=0.5)
        except TimeoutError:
            continue
        envelope = _as_amp(server_key, method, params)
        await runtime.submit(
            CognitiveEvent.create(
                "input.external",
                {
                    "summary": envelope.payload.summary,
                    "amp": amp_to_file_event(envelope),
                    "data": envelope.payload.data,
                },
                source=envelope.header.source.app,
                session_id=envelope.payload.session_id or "system",
                tags={"transport": "mcp", "method": method},
            )
        )


def _as_amp(server_key: str, method: str, params: dict[str, object]) -> AMPEnvelope:
    if method == "aurora/event" and isinstance(params.get("header"), dict) and isinstance(params.get("payload"), dict):
        try:
            return parse_amp_envelope(params)
        except ValueError:
            pass
    raw_data = params.get("data")
    data = (
        {str(key): value for key, value in raw_data.items()}
        if isinstance(raw_data, dict)
        else {"method": method, "params": params}
    )
    return build_event_envelope(
        method="mcp.notification",
        source_app=server_key,
        event_type="capability.changed" if method.endswith("list_changed") else "external.notification",
        session_id=str(params.get("session_id", "")),
        summary=f"MCP notification: {method}",
        data=data,
    )

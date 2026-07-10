"""The deterministic first cognitive node for the RFC 0001 minimum graph."""

from __future__ import annotations

from src.kernel.node import NodeContext


class DecideNode:
    """Translate a received message into one declared local debug effect."""

    def execute(self, context: NodeContext) -> None:
        amp = context.amp
        if amp.payload.type != "message.received":
            return
        text = amp.payload.data.get("text", amp.payload.summary)
        if not isinstance(text, str):
            text = amp.payload.summary
        context.request_effect("debug.echo", {"text": text}, "Echo received message through the local Platform")

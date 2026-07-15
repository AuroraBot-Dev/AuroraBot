"""The deterministic first cognitive node for the RFC 0001 minimum graph."""

from __future__ import annotations

from src.kernel.node import NodeContext
from src.utils.log_utils import get_logger

logger = get_logger("aurora.node.decide")


class DecideNode:
    """Translate a received message into one declared local-console effect."""

    async def execute(self, context: NodeContext) -> None:
        amp = context.amp
        if amp.payload.type != "message.received":
            logger.debug(
                "deterministic node ignored event record_id=%s episode_id=%s node_id=%s event_type=%s",
                context.record.record_id,
                context.record.episode_id,
                context.node_id,
                amp.payload.type,
            )
            return
        text = amp.payload.data.get("text", amp.payload.summary)
        if not isinstance(text, str):
            text = amp.payload.summary
        logger.debug(
            "deterministic console effect selected record_id=%s episode_id=%s node_id=%s text_length=%d",
            context.record.record_id,
            context.record.episode_id,
            context.node_id,
            len(text),
        )
        context.request_effect(
            "org.aurora.console.send_message",
            {"text": text},
            "Send received message through the local console application",
        )

"""Canonical RFC 0016 MCP communication schemas and inbound normalization."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from src.contracts.amp import AmpEnvelope, new_amp

RAW_PUBLICATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "operation": {"type": "string", "enum": ["reply", "relay", "proactive_send"]},
        "route_ref": {"type": ["string", "null"]},
        "address_ref": {"type": ["string", "null"]},
        "text": {"type": "string", "minLength": 1},
        "delivery_id": {"type": "string", "minLength": 1},
        "provenance": {
            "type": "object",
            "properties": {
                "source_endpoint_id": {"type": ["string", "null"]},
                "source_external_event_id": {"type": ["string", "null"]},
                "source_audience_ref": {"type": "string", "minLength": 1},
                "destination_endpoint_id": {"type": "string", "minLength": 1},
                "target_audience_ref": {"type": "string", "minLength": 1},
                "hop_count": {"type": "integer", "minimum": 0},
            },
            "required": [
                "source_endpoint_id",
                "source_external_event_id",
                "source_audience_ref",
                "destination_endpoint_id",
                "target_audience_ref",
                "hop_count",
            ],
            "additionalProperties": False,
        },
    },
    "required": ["operation", "route_ref", "address_ref", "text", "delivery_id", "provenance"],
    "additionalProperties": False,
}


class CommunicationNotificationError(ValueError):
    """A communication App emitted a malformed canonical notification."""


@dataclass(frozen=True, slots=True)
class CanonicalInboundMessage:
    endpoint_id: str
    external_event_id: str
    external_message_id: str
    conversation_ref: str
    actor_ref: str
    reply_route_ref: str
    authored_by_self: bool
    origin_delivery_id: str | None
    summary: str
    text: str

    @classmethod
    def parse(cls, endpoint_id: str, value: dict[str, object]) -> "CanonicalInboundMessage":
        expected = {
            "type",
            "external_event_id",
            "external_message_id",
            "conversation_ref",
            "actor_ref",
            "reply_route_ref",
            "authored_by_self",
            "origin_delivery_id",
            "summary",
            "data",
        }
        if set(value) != expected or value.get("type") != "message.received":
            raise CommunicationNotificationError("message.received has unsupported or missing fields")
        fields = {}
        for name in (
            "external_event_id",
            "external_message_id",
            "conversation_ref",
            "actor_ref",
            "reply_route_ref",
            "summary",
        ):
            item = value.get(name)
            if not isinstance(item, str) or not item:
                raise CommunicationNotificationError(f"message.received {name} must be a non-empty string")
            fields[name] = item
        authored = value.get("authored_by_self")
        if not isinstance(authored, bool):
            raise CommunicationNotificationError("message.received authored_by_self must be boolean")
        origin = value.get("origin_delivery_id")
        if origin is not None and (not isinstance(origin, str) or not origin):
            raise CommunicationNotificationError("message.received origin_delivery_id must be a string or null")
        data = value.get("data")
        if not isinstance(data, dict) or set(data) != {"text"}:
            raise CommunicationNotificationError("message.received data must contain only text")
        text = data.get("text")
        if not isinstance(text, str) or not text:
            raise CommunicationNotificationError("message.received data.text must be a non-empty string")
        return cls(endpoint_id, **fields, authored_by_self=authored, origin_delivery_id=origin, text=text)

    @property
    def audience_ref(self) -> str:
        identity = uuid5(NAMESPACE_URL, f"aurora-mcp-audience:{self.endpoint_id}:{self.conversation_ref}")
        return f"{self.endpoint_id}:{identity}"

    def to_amp(self) -> AmpEnvelope:
        event = new_amp(
            event_type="message.received",
            session_id=self.audience_ref,
            summary=self.summary,
            data={
                "text": self.text,
                "communication": {
                    "endpoint_id": self.endpoint_id,
                    "external_event_id": self.external_event_id,
                    "external_message_id": self.external_message_id,
                    "conversation_ref": self.conversation_ref,
                    "actor_ref": self.actor_ref,
                    "audience_ref": self.audience_ref,
                    "reply_route_ref": self.reply_route_ref,
                    "authored_by_self": self.authored_by_self,
                    "origin_delivery_id": self.origin_delivery_id,
                },
            },
            source_app=self.endpoint_id,
            source_instance=f"mcp:{self.endpoint_id}",
        ).to_dict()
        event["header"]["message_id"] = str(
            uuid5(NAMESPACE_URL, f"aurora-mcp-event:{self.endpoint_id}:{self.external_event_id}")
        )
        return AmpEnvelope.parse(event)


def publication_descriptor_schema(operation: str) -> dict[str, Any]:
    properties: dict[str, Any] = {"text": {"type": "string", "minLength": 1}}
    required = ["text"]
    if operation != "reply":
        properties["destination"] = {"type": "string", "minLength": 1}
        required.append("destination")
    if operation == "proactive_send":
        properties["reason"] = {"type": "string", "minLength": 1}
        required.append("reason")
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }

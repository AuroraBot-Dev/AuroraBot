from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

from src.contracts import (
    AmpEnvelope,
    AmpValidationError,
    capability_event_amp,
)

if TYPE_CHECKING:
    from collections.abc import Callable


def valid_amp() -> dict[str, object]:
    return {
        "header": {
            "protocol": "amp/1.0",
            "method": "aurora/event",
            "message_id": str(uuid4()),
            "timestamp": datetime.now(UTC).isoformat(),
            "source": {"app": "test", "instance": "default"},
        },
        "payload": {
            "type": "message.received",
            "session_id": "session-1",
            "summary": "A test message",
            "data": {"text": "Hello Aurora"},
            "expire_at": None,
        },
    }


def test_parses_supported_amp() -> None:
    envelope = AmpEnvelope.parse(valid_amp())
    assert envelope.payload.type == "message.received"
    assert envelope.to_dict()["header"]["protocol"] == "amp/1.0"


def test_rejects_unsupported_protocol() -> None:
    amp = valid_amp()
    header = amp["header"]
    assert isinstance(header, dict)
    header["protocol"] = "amp/9.0"

    with pytest.raises(AmpValidationError, match="protocol"):
        AmpEnvelope.parse(amp)


@pytest.mark.parametrize(
    "mutation",
    (
        lambda value: value.pop("header"),
        lambda value: value["payload"].update({"data": []}),
        lambda value: value["header"].update({"message_id": "not-a-uuid"}),
    ),
)
def test_rejects_invalid_amp_shapes(mutation: Callable[[dict[str, object]], object]) -> None:
    amp = valid_amp()
    mutation(amp)
    with pytest.raises(AmpValidationError):
        AmpEnvelope.parse(amp)


def test_capability_events_are_stable_idempotent_amp() -> None:
    first = capability_event_amp(
        event_type="capability.registered",
        capability_id="aur.mcp.demo.tool",
        source_app="platform.mcp",
        source_instance="demo",
    )
    second = capability_event_amp(
        event_type="capability.registered",
        capability_id="aur.mcp.demo.tool",
        source_app="platform.mcp",
        source_instance="demo",
    )

    assert first["header"]["message_id"] == second["header"]["message_id"]
    envelope = AmpEnvelope.parse(first)
    assert envelope.payload.type == "capability.registered"
    assert envelope.payload.session_id == "system:capabilities"
    assert envelope.payload.data["capability_id"] == "aur.mcp.demo.tool"


def test_capability_event_rejects_unknown_type() -> None:
    with pytest.raises(ValueError, match="unsupported capability event"):
        capability_event_amp(
            event_type="capability.unknown",
            capability_id="aur.mcp.demo.tool",
            source_app="platform.mcp",
            source_instance="demo",
        )

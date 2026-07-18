from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from src.contracts.amp import AmpEnvelope, AmpValidationError


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
    assert AmpEnvelope.parse(valid_amp()).payload.type == "message.received"


def test_rejects_unsupported_protocol() -> None:
    amp = valid_amp()
    header = amp["header"]
    assert isinstance(header, dict)
    header["protocol"] = "amp/9.0"

    with pytest.raises(AmpValidationError, match="protocol"):
        AmpEnvelope.parse(amp)

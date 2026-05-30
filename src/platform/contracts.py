from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from src.utils.time_utils import now_text


@dataclass(slots=True)
class AppEvent:
    source: str
    type: str
    session_id: str = ""
    summary: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    expire_at: str | None = None
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: str = field(default_factory=now_text)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "type": self.type,
            "session_id": self.session_id,
            "summary": self.summary,
            "payload": self.payload,
            "expire_at": self.expire_at,
            "id": self.id,
            "created_at": self.created_at,
        }


@dataclass(slots=True)
class CommandSpec:
    name: str
    description: str
    parameters_schema: dict[str, Any]
    returns_schema: dict[str, Any]
    handler: Callable[..., Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters_schema": self.parameters_schema,
            "returns_schema": self.returns_schema,
            "handler": str(self.handler),
        }

"""Opaque bearer-token primitives without framework dependencies."""

from __future__ import annotations

import hashlib
import secrets


def new_token() -> str:
    return secrets.token_urlsafe(32)


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()

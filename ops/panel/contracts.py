"""Panel 后端设置与认证会话值对象。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from datetime import datetime

_MAX_PORT = 65535


@dataclass(frozen=True, slots=True)
class PanelSettings:
    host: str = "127.0.0.1"
    port: int = 8765
    allowed_origins: tuple[str, ...] = ()
    session_ttl_seconds: int = 86400
    profile: str = "default"

    def __post_init__(self) -> None:
        object.__setattr__(self, "allowed_origins", tuple(self.allowed_origins))
        if not self.host.strip():
            raise ValueError("Panel host 不能为空")
        if not 1 <= self.port <= _MAX_PORT:
            raise ValueError("Panel port 必须在 1 到 65535 之间")
        if self.session_ttl_seconds <= 0:
            raise ValueError("Panel session_ttl_seconds 必须大于 0")
        if not self.profile.strip():
            raise ValueError("Panel profile 不能为空")
        if any(not origin or origin == "*" for origin in self.allowed_origins):
            raise ValueError("Panel allowed_origins 必须是明确的非空来源")


@dataclass(frozen=True, slots=True)
class PanelSession:
    token: str
    created_at: datetime
    expires_at: datetime

    def to_dict(self) -> dict[str, Any]:
        return {
            "token": self.token,
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
        }

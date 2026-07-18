"""Transport-neutral input and command contracts for localhost use cases."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from src.contracts.configuration import AuroraConfig


class InputOrigin(StrEnum):
    CONSOLE = "console"
    DASHBOARD = "dashboard"


class CommandControl(StrEnum):
    NONE = "none"
    SHUTDOWN_PROCESS = "shutdown_process"


@dataclass(frozen=True, slots=True)
class RuntimeInput:
    """Normalized text input supplied by a local transport adapter."""

    text: str
    origin: InputOrigin
    session_id: str
    source_app: str
    source_instance: str
    reply_capability: str
    actor_id: str | None = None
    idempotency_key: str | None = None
    data: dict[str, Any] = field(default_factory=dict)

    def with_text(self, text: str) -> "RuntimeInput":
        return RuntimeInput(
            text=text,
            origin=self.origin,
            session_id=self.session_id,
            source_app=self.source_app,
            source_instance=self.source_instance,
            reply_capability=self.reply_capability,
            actor_id=self.actor_id,
            idempotency_key=self.idempotency_key,
            data=dict(self.data),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class CommandResult:
    """A transport-independent result returned by input routing."""

    ok: bool
    text: str | None = None
    data: dict[str, Any] | None = None
    message_id: str | None = None
    publish_reply: bool = True
    control: CommandControl = CommandControl.NONE


class RuntimeCommandPort(Protocol):
    configuration: AuroraConfig

    async def submit_amp(self, value: object) -> str: ...

    async def submit_conversation(self, request: RuntimeInput, text: str) -> str: ...

    async def pump(self, max_turns: int | None = None) -> dict[str, Any]: ...

    def status(self) -> dict[str, Any]: ...

    def task(self, task_id: str) -> dict[str, Any] | None: ...

    def agent(self, agent_id: str) -> dict[str, Any] | None: ...


@dataclass(frozen=True, slots=True)
class CommandContext:
    runtime: RuntimeCommandPort
    request: RuntimeInput

"""MCP 业务事件扩展与启动门闩。"""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 - Pydantic 在运行时解析动态子类字段
from typing import TYPE_CHECKING, Any, Self

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, model_validator

from mcp.client.extension import ClientExtension, NotificationBinding
from src.mcp.models import McpInboundEvent

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

WORLD_EVENTS_EXTENSION = "org.aurorabot/world-events"
WORLD_EVENT_NOTIFICATION = "notifications/org.aurorabot/world-events/event"

type InboundEventHandler = Callable[[McpInboundEvent], Awaitable[None]]


class WorldEventParams(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str = Field(min_length=1)
    scope: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    occurred_at: datetime
    summary: str = Field(min_length=1)
    data: dict[str, Any] = Field(default_factory=dict)
    _arrival_generation: int = PrivateAttr(default=-1)


class InboundEventGate:
    """用 arrival generation 拒绝启动与关闭窗口中的排队通知。"""

    def __init__(self, handler: InboundEventHandler) -> None:
        self._handler = handler
        self._generation = 0
        self._active = False

    def snapshot(self) -> int:
        return self._generation

    def accepts(self, generation: int) -> bool:
        return self._active and generation == self._generation

    def activate(self) -> None:
        if not self._active:
            self._generation += 1
            self._active = True

    def deactivate(self) -> None:
        if self._active:
            self._generation += 1
            self._active = False

    async def deliver(self, arrival_generation: int, event: McpInboundEvent) -> None:
        if self.accepts(arrival_generation):
            await self._handler(event)


def _gated_event_params(gate: InboundEventGate) -> type[WorldEventParams]:
    class GatedWorldEventParams(WorldEventParams):
        _arrival_generation: int = PrivateAttr(default_factory=gate.snapshot)

        @model_validator(mode="after")
        def validate_gate(self) -> Self:
            if not gate.accepts(self._arrival_generation):
                raise ValueError("MCP 业务事件尚未激活")
            return self

    return GatedWorldEventParams


class WorldEventsExtension(ClientExtension):
    identifier = WORLD_EVENTS_EXTENSION

    def __init__(self, gate: InboundEventGate) -> None:
        self._gate = gate
        self._params_type = _gated_event_params(gate)

    def settings(self) -> dict[str, Any]:
        return {"version": 1}

    def notifications(self) -> tuple[NotificationBinding[WorldEventParams], ...]:
        return (
            NotificationBinding(
                method=WORLD_EVENT_NOTIFICATION,
                params_type=self._params_type,
                handler=self._handle,
            ),
        )

    async def _handle(self, params: WorldEventParams) -> None:
        await self._gate.deliver(params._arrival_generation, inbound_event(params))


def inbound_event(params: WorldEventParams) -> McpInboundEvent:
    return McpInboundEvent(
        params.event_id,
        params.scope,
        params.kind,
        params.occurred_at,
        params.summary,
        params.data,
    )


__all__ = [
    "WORLD_EVENTS_EXTENSION",
    "WORLD_EVENT_NOTIFICATION",
    "InboundEventGate",
    "InboundEventHandler",
    "WorldEventParams",
    "WorldEventsExtension",
    "inbound_event",
]

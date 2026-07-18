"""In-process Platform adapter for Dashboard reply effects."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from src.contracts.agent import EffectLease, PlatformRuntimePort
from src.contracts.amp import AmpEnvelope, new_amp
from src.platform.effects import PlatformRunResult
from src.utils.log_utils import get_logger

logger = get_logger("aurora.platform.dashboard")

DASHBOARD_REPLY_CAPABILITY = "org.aurora.dashboard.send_message"
ReplySink = Callable[[str, str, str], Awaitable[dict[str, Any]]]


class DashboardPlatform:
    """Execute Dashboard publication effects through an injected localhost sink."""

    def __init__(self, sink: ReplySink) -> None:
        self._sink = sink

    async def execute_pending_effects(self, kernel: PlatformRuntimePort) -> PlatformRunResult:
        records = await kernel.claim_effect_requests(frozenset({DASHBOARD_REPLY_CAPABILITY}))
        completed = await asyncio.gather(*(self._execute_one(kernel, record) for record in records))
        return PlatformRunResult(sum(completed))

    async def _execute_one(self, kernel: PlatformRuntimePort, record: EffectLease) -> int:
        amp = AmpEnvelope.parse(record.amp)
        data = amp.payload.data
        request_id = data.get("request_id")
        parameters = data.get("parameters")
        try:
            if not isinstance(request_id, str) or not isinstance(parameters, dict):
                raise ValueError("dashboard effect payload is invalid")
            text = parameters.get("text")
            if not isinstance(text, str) or not text:
                raise ValueError("dashboard reply text is invalid")
            message = await self._sink(amp.payload.session_id, text, request_id)
            receipt = new_amp(
                event_type="effect.succeeded",
                session_id=amp.payload.session_id,
                summary="Dashboard reply delivered",
                data={
                    "request_id": request_id,
                    "capability": DASHBOARD_REPLY_CAPABILITY,
                    "result": {"message_id": message["message_id"]},
                },
                source_app="platform.dashboard",
                source_instance="local",
            )
            await kernel.submit_amp(receipt)
            await kernel.complete_effect(record)
            logger.info(
                "dashboard effect succeeded activity_id=%s task_id=%s request_id=%s",
                record.record_id,
                record.task_id,
                request_id,
            )
        except Exception as error:  # noqa: BLE001 - effects must become audited failure receipts.
            request_value = request_id if isinstance(request_id, str) else "invalid"
            receipt = new_amp(
                event_type="effect.failed",
                session_id=amp.payload.session_id,
                summary="Dashboard reply failed",
                data={
                    "request_id": request_value,
                    "capability": DASHBOARD_REPLY_CAPABILITY,
                    "error": f"{type(error).__name__}: {error}",
                },
                source_app="platform.dashboard",
                source_instance="local",
            )
            await kernel.submit_amp(receipt)
            await kernel.complete_effect(record, error=f"{type(error).__name__}: {error}")
            logger.log(
                logging.ERROR,
                "dashboard effect failed activity_id=%s task_id=%s request_id=%s error_type=%s",
                record.record_id,
                record.task_id,
                request_value,
                type(error).__name__,
            )
        return 1

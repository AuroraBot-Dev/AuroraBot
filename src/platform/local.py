"""A local Platform adapter used by the first causal-loop integration tests."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass

from src.kernel.contracts import EffectLease, PlatformRuntimePort
from src.kernel.events import AmpEnvelope, new_amp
from src.utils.log_utils import get_logger

logger = get_logger("aurora.platform.local")


@dataclass(frozen=True, slots=True)
class PlatformRunResult:
    receipts_emitted: int


class LocalTestPlatform:
    """Execute the console capability in deterministic localhost tests."""

    def __init__(self, capabilities: frozenset[str] = frozenset()) -> None:
        self.capabilities = capabilities

    async def execute_pending_effects(self, kernel: PlatformRuntimePort) -> PlatformRunResult:
        records = await kernel.claim_effect_requests(self.capabilities)
        completed = await asyncio.gather(*(self._execute_one(kernel, record) for record in records))
        return PlatformRunResult(sum(completed))

    async def _execute_one(self, kernel: PlatformRuntimePort, record: EffectLease) -> int:
        started = time.monotonic()
        amp = AmpEnvelope.parse(record.amp)
        data = amp.payload.data
        request_id = data.get("request_id")
        if not isinstance(request_id, str):
            await kernel.complete_effect(record, error="effect.requested lacks request_id")
            logger.error(
                "invalid local effect request activity_id=%s task_id=%s reason=missing_request_id",
                record.record_id,
                record.task_id,
            )
            return 0
        try:
            parameters = data["parameters"]
            if not isinstance(parameters, dict) or not isinstance(parameters.get("text"), str):
                raise ValueError("org.aurora.console.send_message requires string parameters.text")
            receipt = new_amp(
                event_type="effect.succeeded",
                session_id=amp.payload.session_id,
                summary="Local test effect completed",
                data={
                    "request_id": request_id,
                    "capability": "org.aurora.console.send_message",
                    "result": {"text": parameters["text"]},
                },
                source_app="platform.local",
                source_instance="test",
            )
            await kernel.submit_amp(receipt)
            await kernel.complete_effect(record)
            logger.info(
                "local effect succeeded activity_id=%s task_id=%s request_id=%s capability=%s duration_ms=%.1f",
                record.record_id,
                record.task_id,
                request_id,
                data.get("capability"),
                (time.monotonic() - started) * 1000,
            )
        except Exception as error:  # noqa: BLE001 - Platform failures must return an AMP receipt.
            receipt = new_amp(
                event_type="effect.failed",
                session_id=amp.payload.session_id,
                summary="Local test effect failed",
                data={
                    "request_id": request_id,
                    "capability": data.get("capability"),
                    "error": f"{type(error).__name__}: {error}",
                },
                source_app="platform.local",
                source_instance="test",
            )
            await kernel.submit_amp(receipt)
            await kernel.complete_effect(record, error=f"{type(error).__name__}: {error}")
            logger.log(
                logging.ERROR,
                "local effect failed activity_id=%s task_id=%s request_id=%s "
                "capability=%s duration_ms=%.1f error_type=%s",
                record.record_id,
                record.task_id,
                request_id,
                data.get("capability"),
                (time.monotonic() - started) * 1000,
                type(error).__name__,
            )
        return 1

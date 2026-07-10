"""A local Platform adapter used by the first causal-loop integration tests."""

from __future__ import annotations

from dataclasses import dataclass

from src.kernel.events import AmpEnvelope, new_amp
from src.kernel.runtime import Kernel


@dataclass(frozen=True, slots=True)
class PlatformRunResult:
    receipts_emitted: int


class LocalDebugPlatform:
    """Execute only the deterministic ``debug.echo`` capability."""

    capabilities = frozenset({"debug.echo"})

    async def execute_pending_effects(self, kernel: Kernel) -> PlatformRunResult:
        receipts = 0
        for record in await kernel.claim_effect_requests(self.capabilities):
            amp = AmpEnvelope.parse(record.amp)
            data = amp.payload.data
            request_id = data.get("request_id")
            if not isinstance(request_id, str):
                kernel.complete_effect(record, error="effect.requested lacks request_id")
                continue
            try:
                parameters = data["parameters"]
                if not isinstance(parameters, dict) or not isinstance(parameters.get("text"), str):
                    raise ValueError("debug.echo requires string parameters.text")
                receipt = new_amp(
                    event_type="effect.succeeded",
                    session_id=amp.payload.session_id,
                    summary="Local debug effect completed",
                    data={
                        "request_id": request_id,
                        "capability": "debug.echo",
                        "result": {"echo": parameters["text"]},
                    },
                    source_app="platform.local",
                    source_instance="debug",
                )
                await kernel.submit_amp(receipt)
                kernel.complete_effect(record)
                receipts += 1
            except Exception as error:  # noqa: BLE001 - Platform failures must return an AMP receipt.
                receipt = new_amp(
                    event_type="effect.failed",
                    session_id=amp.payload.session_id,
                    summary="Local debug effect failed",
                    data={
                        "request_id": request_id,
                        "capability": data.get("capability"),
                        "error": f"{type(error).__name__}: {error}",
                    },
                    source_app="platform.local",
                    source_instance="debug",
                )
                await kernel.submit_amp(receipt)
                kernel.complete_effect(record, error=f"{type(error).__name__}: {error}")
                receipts += 1
        return PlatformRunResult(receipts)

"""Composition root for the locally runnable minimal causal loop."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from threading import RLock
from typing import Any

from src.config import AuroraConfig, load_config
from src.kernel.events import AmpEnvelope
from src.kernel.runtime import CycleResult, Kernel
from src.nodes.decide import DecideNode
from src.platform.local import LocalDebugPlatform


@dataclass(slots=True)
class AuroraRuntime:
    """Coordinates the local use case without exposing Kernel to HTTP callers."""

    configuration: AuroraConfig
    kernel: Kernel
    platform: LocalDebugPlatform
    _lock: RLock = field(default_factory=RLock, repr=False)

    @classmethod
    def create(cls, root: Path, profile: str | None = None) -> "AuroraRuntime":
        configuration = load_config(root, profile)
        nodes = {"builtin.decide": DecideNode()}
        return cls(configuration, Kernel(configuration, nodes), LocalDebugPlatform())

    def submit_amp(self, value: object) -> str:
        amp = AmpEnvelope.parse(value)
        self.kernel.submit_amp(amp)
        return amp.header.message_id

    def run_cycle(self) -> dict[str, Any]:
        with self._lock:
            result: CycleResult = self.kernel.run_cycle()
            platform_result = self.platform.execute_pending_effects(self.kernel)
            response = result.to_dict()
            response["platform_receipts_emitted"] = platform_result.receipts_emitted
            return response

    def record(self, record_id: str) -> dict[str, Any] | None:
        record = self.kernel.get_record(record_id)
        return record.to_dict() if record else None

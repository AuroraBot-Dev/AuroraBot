"""Composition root for the locally runnable minimal causal loop."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.ai.vnext import ModelGatewayService
from src.config import AuroraConfig, load_config
from src.kernel.events import AmpEnvelope
from src.kernel.runtime import CycleResult, Kernel
from src.nodes.decide import DecideNode
from src.nodes.model_decide import ModelDecideNode
from src.platform.local import LocalDebugPlatform


@dataclass(slots=True)
class AuroraRuntime:
    """Coordinates the local use case without exposing Kernel to HTTP callers."""

    configuration: AuroraConfig
    kernel: Kernel
    platform: LocalDebugPlatform
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)

    @classmethod
    def create(cls, root: Path, profile: str | None = None) -> "AuroraRuntime":
        configuration = load_config(root, profile)
        nodes = {
            "builtin.decide": DecideNode(),
            "builtin.model_decide": ModelDecideNode(),
        }
        enabled_nodes = {node.id: nodes[node.id] for node in configuration.nodes}
        return cls(
            configuration,
            Kernel(configuration, enabled_nodes, ModelGatewayService(configuration)),
            LocalDebugPlatform(),
        )

    async def submit_amp(self, value: object) -> str:
        amp = AmpEnvelope.parse(value)
        await self.kernel.submit_amp(amp)
        return amp.header.message_id

    async def run_cycle(self) -> dict[str, Any]:
        async with self._lock:
            result: CycleResult = await self.kernel.run_cycle()
            platform_result = await self.platform.execute_pending_effects(self.kernel)
            response = result.to_dict()
            response["platform_receipts_emitted"] = platform_result.receipts_emitted
            return response

    def record(self, record_id: str) -> dict[str, Any] | None:
        record = self.kernel.get_record(record_id)
        return record.to_dict() if record else None

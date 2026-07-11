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
from src.platform.local import LocalTestPlatform
from src.platform.mcp_platform import MCPPlatform


@dataclass(slots=True)
class AuroraRuntime:
    """Coordinates the local use case without exposing Kernel to HTTP callers."""

    configuration: AuroraConfig
    kernel: Kernel
    platform: LocalTestPlatform
    mcp_platform: MCPPlatform
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)
    _started: bool = field(default=False, init=False, repr=False)
    _console_messages: list[str] = field(default_factory=list, init=False, repr=False)

    @classmethod
    def create(cls, root: Path, profile: str | None = None) -> "AuroraRuntime":
        configuration = load_config(root, profile)
        nodes = {
            "builtin.decide": DecideNode(),
            "builtin.model_decide": ModelDecideNode(),
        }
        enabled_nodes = {node.id: nodes[node.id] for node in configuration.nodes}
        test_capabilities = frozenset(
            capability.id
            for adapter in configuration.adapters
            if adapter.implementation == "src.platform.local:LocalTestPlatform"
            for capability in adapter.capabilities
        )
        runtime = cls(
            configuration,
            Kernel(configuration, enabled_nodes, ModelGatewayService(configuration)),
            LocalTestPlatform(test_capabilities),
            MCPPlatform(configuration),
        )
        runtime.mcp_platform.set_tool_result_observer(runtime._observe_mcp_result)
        return runtime

    async def _ensure_started(self) -> None:
        if not self._started:
            await self.mcp_platform.start(self.kernel)
            self._started = True

    async def submit_amp(self, value: object) -> str:
        await self._ensure_started()
        amp = AmpEnvelope.parse(value)
        await self.kernel.submit_amp(amp)
        return amp.header.message_id

    async def run_cycle(self) -> dict[str, Any]:
        async with self._lock:
            await self._ensure_started()
            result: CycleResult = await self.kernel.run_cycle()
            platform_result = await self.platform.execute_pending_effects(self.kernel)
            mcp_result = await self.mcp_platform.execute_pending_effects(self.kernel)
            response = result.to_dict()
            response["platform_receipts_emitted"] = platform_result.receipts_emitted + mcp_result.receipts_emitted
            return response

    async def shutdown(self) -> None:
        await self.mcp_platform.shutdown()

    def drain_console_messages(self) -> tuple[str, ...]:
        """Return and clear messages delivered by the console MCP application."""
        messages = tuple(self._console_messages)
        self._console_messages.clear()
        return messages

    def _observe_mcp_result(self, capability: str, result: dict[str, object]) -> None:
        if capability != "org.aurora.console.send_message" or result.get("ok") is not True:
            return
        text = result.get("text")
        if isinstance(text, str) and text:
            self._console_messages.append(text)

    def record(self, record_id: str) -> dict[str, Any] | None:
        record = self.kernel.get_record(record_id)
        return record.to_dict() if record else None

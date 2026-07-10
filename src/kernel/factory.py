# ruff: noqa: ARG002, TRY003
"""Assembly of AuroraBot's cognitive runtime and host capabilities."""

from __future__ import annotations

from typing import Any

from src.ai.gateway import gateway
from src.kernel.registry import NodeRegistry
from src.kernel.runtime import CognitiveRuntime, RuntimeServices
from src.memory import get_memory_manager
from src.nodes import plugins


class UnavailableMcpCapability:
    def tools_as_prompt_text(self) -> str:
        return "（MCP capability 尚未连接）"

    async def call_tool(self, tool_name: str, arguments: dict[str, object]) -> dict[str, object]:
        raise RuntimeError(f"MCP capability unavailable for tool: {tool_name}")


def build_node_registry() -> NodeRegistry:
    registry = NodeRegistry()
    registry.discover()
    for plugin in plugins():
        if not registry.has(plugin.node_type):
            registry.register(plugin)
    return registry


def build_cognitive_runtime(*, client_manager: Any | None = None) -> CognitiveRuntime:
    services = RuntimeServices(
        gateway=gateway,
        mcp=client_manager or UnavailableMcpCapability(),
        memory=get_memory_manager(),
    )
    return CognitiveRuntime(build_node_registry(), services)

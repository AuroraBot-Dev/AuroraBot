from __future__ import annotations

from typing import TYPE_CHECKING

from src.config.loader import load_configuration
from src.contracts import (
    AgentContext,
    AgentDecision,
    Completion,
    EngineConfiguration,
    ModelResult,
    ModelUsage,
    TriageLimits,
)
from src.engine.runtime import AgentEngine
from src.localhost.runtime import AuroraRuntime

if TYPE_CHECKING:
    from pathlib import Path

    from src.contracts.agent import AgentHandler
    from src.contracts.model import ModelRequest


class CompletingHandler:
    def handle(self, context: AgentContext) -> AgentDecision:
        return AgentDecision(completion=Completion(f"completed: {context.task.root_summary}"))


class TriageModelProvider:
    async def complete(self, request: ModelRequest) -> ModelResult:
        return ModelResult(
            request.role,
            frozenset({"chat", "structured_output"}),
            "normalized",
            "",
            {"action": "process", "summary": "test batch", "reason": "test input"},
            ModelUsage(),
            0.0,
        )


def create_test_runtime(root: Path) -> AuroraRuntime:
    configuration = load_configuration(root)
    engine_configuration = EngineConfiguration(
        workspace=str(configuration.engine.workspace),
        profiles=configuration.agents,
        limits=configuration.engine.agents,
        interactive_budget=configuration.engine.interactive_budget,
        autonomous_budget=configuration.engine.autonomous_budget,
        triage=TriageLimits(quiet_seconds=0, max_wait_seconds=0.001),
    )
    handlers: dict[str, AgentHandler] = dict.fromkeys(
        (profile.id for profile in configuration.agents), CompletingHandler()
    )
    engine = AgentEngine(
        engine_configuration,
        handlers,
        model_provider=TriageModelProvider(),
    )
    engine.bind_tool_executors(())
    return AuroraRuntime(configuration, engine)

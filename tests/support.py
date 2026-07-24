from __future__ import annotations

from typing import TYPE_CHECKING

from src.config.loader import load_configuration
from src.contracts.agent import AgentContext, AgentDecision, Completion, EngineConfiguration
from src.engine.runtime import AgentEngine
from src.localhost.runtime import AuroraRuntime

if TYPE_CHECKING:
    from pathlib import Path

    from src.contracts.agent import AgentHandler
    from src.contracts.model import ModelRequest, ModelResult


class CompletingHandler:
    def handle(self, context: AgentContext) -> AgentDecision:
        return AgentDecision(completion=Completion(f"completed: {context.task.root_summary}"))


class UnusedModelProvider:
    async def complete(self, request: ModelRequest) -> ModelResult:
        raise AssertionError(f"unexpected model request: {request.role}")


def create_test_runtime(root: Path) -> AuroraRuntime:
    configuration = load_configuration(root)
    engine_configuration = EngineConfiguration(
        workspace=str(configuration.engine.workspace),
        profiles=configuration.agents,
        limits=configuration.engine.agents,
        interactive_budget=configuration.engine.interactive_budget,
        autonomous_budget=configuration.engine.autonomous_budget,
    )
    handlers: dict[str, AgentHandler] = dict.fromkeys(
        (profile.id for profile in configuration.agents), CompletingHandler()
    )
    engine = AgentEngine(engine_configuration, handlers, model_provider=UnusedModelProvider())
    engine.bind_tool_executors(())
    return AuroraRuntime(configuration, engine)

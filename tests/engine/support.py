"""该能力测试共用的离线替身与场景构造。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from aurora_bot.agents import AgentCatalog
from aurora_bot.contracts import (
    AgentDefinition,
    ChatMessage,
    EnvironmentEvent,
    ModelRequest,
    Tool,
    ToolCall,
    ToolDefinition,
    ToolOutput,
    ToolScopes,
    ToolStatus,
)
from aurora_bot.engine import AgentTreeRunner
from aurora_bot.prompt import PromptAssembler
from aurora_bot.tools import DelegateTool, ToolRegistry
from tests.support.model import FakeModelDirectory
from tests.support.prompt import make_prompt_catalog

if TYPE_CHECKING:
    from aurora_bot.contracts.pkgs.ai import Model
    from aurora_bot.contracts.pkgs.world import WorldJournal
    from aurora_bot.world import SqlAlchemyWorldJournal


EXPECTED_DELEGATION_NODES = 2


_SECOND_REQUEST = 2


_EXPECTED_SCOPE_SEQUENCE = 5


class EchoTool:
    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            "test:tool/definition/echo",
            "Echo one value.",
            {"type": "object", "properties": {"value": {"type": "string"}}, "required": ["value"]},
        )

    async def execute(self, call: ToolCall) -> ToolOutput:
        return ToolOutput(str(call.arguments["value"]))


class FailingTool(EchoTool):
    async def execute(self, call: ToolCall) -> ToolOutput:
        raise RuntimeError(str(call.arguments.get("error", "broken")))


class UnknownTool(EchoTool):
    def __init__(self) -> None:
        self.calls = 0

    async def execute(self, call: ToolCall) -> ToolOutput:
        self.calls += 1
        return ToolOutput(str(call.arguments["value"]), status=ToolStatus.UNKNOWN)


class ScopedEchoTool(EchoTool):
    def __init__(self, scope: str) -> None:
        self.scope = scope
        self.values: list[str] = []

    def resolve_scopes(self, call: ToolCall) -> ToolScopes:
        _ = call
        return ToolScopes(observe=frozenset({self.scope}), publish=frozenset({self.scope}))

    async def execute(self, call: ToolCall) -> ToolOutput:
        value = str(call.arguments["value"])
        self.values.append(value)
        return ToolOutput(value)


@dataclass(slots=True)
class EventInjectingModel(FakeModelDirectory):
    responses: list[ChatMessage]
    journal: SqlAlchemyWorldJournal
    event: EnvironmentEvent
    requests: list[ModelRequest] = field(default_factory=list)

    async def complete(self, request: ModelRequest) -> ChatMessage:
        self.requests.append(request)
        if len(self.requests) == _SECOND_REQUEST:
            await self.journal.append_event(self.event)
        return self.responses.pop(0)


def _prompt_id(name: str) -> str:
    return f"aurora:prompt/agent/{name}"


def _agent_id(name: str) -> str:
    return f"aurora:agent/definition/{name}"


def _assembler() -> PromptAssembler:
    return PromptAssembler(
        make_prompt_catalog(
            ("You are Aurora.",),
            {_prompt_id("root"): "Solve the whole task.", _prompt_id("worker"): "Solve only the assigned part."},
        )
    )


def _agent(
    definition_id: str = "root",
    prompt: str = "root",
    model: str = "model",
    tools: frozenset[str] = frozenset(),
    children: frozenset[str] = frozenset(),
) -> AgentDefinition:
    return AgentDefinition(
        _agent_id(definition_id),
        f"{definition_id} Agent.",
        _prompt_id(prompt),
        f"test:ai/endpoint/{model}",
        tools,
        frozenset(_agent_id(child) for child in children),
    )


def _runner(
    model: Model,
    definitions: tuple[AgentDefinition, ...],
    *tools: Tool,
    world: WorldJournal | None = None,
) -> AgentTreeRunner:
    agents = AgentCatalog(definitions)
    registry = ToolRegistry((DelegateTool(agents), *tools))
    return AgentTreeRunner(model, _assembler(), agents, registry, world=world)

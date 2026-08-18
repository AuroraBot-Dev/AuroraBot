from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from aurora import (
    AuroraConfiguration,
    PromptConfiguration,
    RootAgentConfiguration,
    assemble_runtime,
    load_configuration,
)
from aurora.composition.engine import assemble_engine
from aurora.composition.prompt import assemble_prompt
from src.contracts import ChatMessage, ModelRequest, TreeStatus


@dataclass(slots=True)
class FakeModel:
    requests: list[ModelRequest] = field(default_factory=list)

    async def complete(self, request: ModelRequest) -> ChatMessage:
        self.requests.append(request)
        return ChatMessage.assistant("done")


def test_project_configuration_builds_complete_runtime() -> None:
    configuration = load_configuration(Path(__file__).parents[1])
    model = FakeModel()
    runtime = assemble_runtime(configuration, model)

    result = asyncio.run(runtime.run("hello", tree_id="tree"))

    assert result.status == TreeStatus.COMPLETED
    assert result.tree_id == "tree"
    assert result.node(configuration.root.node_id).model == configuration.root.model
    assert model.requests[0].model == configuration.root.model
    assert [tool.name for tool in model.requests[0].tools] == ["delegate"]


def test_assembly_rejects_unavailable_root_tool() -> None:
    configuration = load_configuration(Path(__file__).parents[1])
    invalid = AuroraConfiguration(
        RootAgentConfiguration(
            configuration.root.node_id,
            configuration.root.profile,
            configuration.root.model,
            frozenset({"missing"}),
        ),
        configuration.runner,
        configuration.prompt,
    )

    with pytest.raises(ValueError, match="unavailable tools"):
        assemble_runtime(invalid, FakeModel())


def test_configuration_is_pure_data_until_composition_stages_run() -> None:
    configuration = load_configuration(Path(__file__).parents[1])

    assert isinstance(configuration.prompt, PromptConfiguration)
    assembler = assemble_prompt(configuration)
    runner = assemble_engine(configuration, FakeModel(), assembler)

    assert runner is not None

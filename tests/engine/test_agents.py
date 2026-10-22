from __future__ import annotations

import pytest

from aurora_bot.agents import AgentCatalog, AgentDefinitionError
from aurora_bot.contracts import AgentDefinition


def _agent(definition_id: str) -> AgentDefinition:
    return AgentDefinition(
        f"aurora:agent/definition/{definition_id}",
        f"{definition_id} Agent.",
        "aurora:prompt/agent/shared",
        "test:ai/endpoint/model",
        frozenset(),
    )


def test_catalog_is_sorted_unique_and_resolves_definitions() -> None:
    worker = _agent("worker")
    root = _agent("root")
    catalog = AgentCatalog((worker, root))

    assert [definition.definition_id for definition in catalog.definitions] == [
        "aurora:agent/definition/root",
        "aurora:agent/definition/worker",
    ]
    assert catalog.ids == frozenset({"aurora:agent/definition/root", "aurora:agent/definition/worker"})
    assert catalog.get("aurora:agent/definition/worker") is worker


def test_catalog_rejects_empty_duplicate_unknown_and_missing_child_definitions() -> None:
    with pytest.raises(AgentDefinitionError, match="至少需要"):
        AgentCatalog(())
    with pytest.raises(AgentDefinitionError, match="重复注册"):
        AgentCatalog((_agent("root"), _agent("root")))
    with pytest.raises(AgentDefinitionError, match="未知 Agent definition"):
        AgentCatalog((_agent("root"),)).get("aurora:agent/definition/missing")


def test_agent_definition_requires_complete_identity_and_non_empty_references() -> None:
    with pytest.raises(ValueError, match="definition ID"):
        AgentDefinition("", "Agent.", "aurora:prompt/agent/profile", "test:ai/endpoint/model", frozenset())
    with pytest.raises(ValueError, match="非工具 ID"):
        AgentDefinition(
            "aurora:agent/definition/root",
            "Agent.",
            "aurora:prompt/agent/profile",
            "test:ai/endpoint/model",
            frozenset({""}),
        )

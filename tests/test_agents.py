from __future__ import annotations

import pytest

from src.agents import AgentCatalog, AgentDefinitionError
from src.contracts import AgentDefinition


def _agent(definition_id: str, *, children: frozenset[str] = frozenset()) -> AgentDefinition:
    return AgentDefinition(definition_id, f"{definition_id} Agent.", "shared", "model", frozenset(), children)


def test_catalog_is_sorted_unique_and_resolves_definitions() -> None:
    worker = _agent("worker")
    root = _agent("root", children=frozenset({"worker"}))
    catalog = AgentCatalog((worker, root))

    assert [definition.definition_id for definition in catalog.definitions] == ["root", "worker"]
    assert catalog.ids == frozenset({"root", "worker"})
    assert catalog.get("worker") is worker


def test_catalog_rejects_empty_duplicate_unknown_and_missing_child_definitions() -> None:
    with pytest.raises(AgentDefinitionError, match="至少需要"):
        AgentCatalog(())
    with pytest.raises(AgentDefinitionError, match="重复注册"):
        AgentCatalog((_agent("root"), _agent("root")))
    with pytest.raises(AgentDefinitionError, match="未知 child"):
        AgentCatalog((_agent("root", children=frozenset({"missing"})),))
    with pytest.raises(AgentDefinitionError, match="未知 Agent definition"):
        AgentCatalog((_agent("root"),)).get("missing")


def test_agent_definition_requires_complete_identity_and_non_empty_references() -> None:
    with pytest.raises(ValueError, match="requires definition_id"):
        AgentDefinition("", "Agent.", "profile", "model", frozenset(), frozenset())
    with pytest.raises(ValueError, match="must not be empty"):
        AgentDefinition("root", "Agent.", "profile", "model", frozenset({""}), frozenset())

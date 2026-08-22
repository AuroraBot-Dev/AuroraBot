from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import pytest

from src.agents import AgentCatalog
from src.contracts import (
    AgentDefinition,
    DelegationRequest,
    EnvironmentEvent,
    ToolCall,
    ToolDefinition,
    ToolOutput,
    TreeActivity,
    WorldCommit,
    WorldCommitInput,
    WorldDeltaPage,
    WorldFrontier,
)
from src.tools import (
    DELEGATE_TOOL,
    WORLD_READ_TOOL,
    WORLD_TREES_TOOL,
    DelegateTool,
    ToolRegistrationError,
    ToolRegistry,
    WorldReadTool,
    WorldTreesTool,
)

if TYPE_CHECKING:
    from collections.abc import Mapping


class EchoTool:
    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition("aur.test.echo", "回显一个值。", {"type": "object"})

    async def execute(self, call: ToolCall) -> ToolOutput:
        return ToolOutput(str(call.arguments["value"]))


class FailingTool(EchoTool):
    async def execute(self, call: ToolCall) -> ToolOutput:
        raise RuntimeError(str(call.arguments["error"]))


def _agents() -> AgentCatalog:
    return AgentCatalog(
        (
            AgentDefinition(
                "root",
                "总代理。",
                "root",
                "quality",
                frozenset({DELEGATE_TOOL}),
                frozenset({"worker"}),
            ),
            AgentDefinition("worker", "通用执行者。", "worker", "fast", frozenset(), frozenset()),
        )
    )


def test_registry_forms_sorted_immutable_catalog_and_filters_visibility() -> None:
    registry = ToolRegistry((EchoTool(), DelegateTool(_agents())))

    assert registry.names == frozenset({DELEGATE_TOOL, "aur.test.echo"})
    assert [definition.name for definition in registry.definitions] == [DELEGATE_TOOL, "aur.test.echo"]
    assert [definition.name for definition in registry.definitions_for(frozenset({"aur.test.echo"}))] == [
        "aur.test.echo"
    ]


def test_registry_rejects_non_domain_and_duplicate_tool_ids() -> None:
    class InvalidTool(EchoTool):
        @property
        def definition(self) -> ToolDefinition:
            return ToolDefinition("echo", "无效名称。", {})

    with pytest.raises(ToolRegistrationError, match=r"aur\.\*"):
        ToolRegistry((InvalidTool(),))
    with pytest.raises(ToolRegistrationError, match="重复注册"):
        ToolRegistry((EchoTool(), EchoTool()))


def test_registry_routes_calls_and_normalizes_boundary_failures() -> None:
    with pytest.raises(ToolRegistrationError, match="重复注册"):
        ToolRegistry((EchoTool(), FailingTool()))

    echo = asyncio.run(ToolRegistry((EchoTool(),)).execute(ToolCall("echo", "aur.test.echo", {"value": "ok"})))
    missing = asyncio.run(ToolRegistry().execute(ToolCall("missing", "aur.test.missing", {})))
    failed = asyncio.run(
        ToolRegistry((FailingTool(),)).execute(ToolCall("failed", "aur.test.echo", {"error": "broken"}))
    )

    assert echo == ToolOutput("ok")
    assert missing == ToolOutput("未知工具：aur.test.missing", is_error=True)
    assert failed == ToolOutput("工具执行失败：broken", is_error=True)


def test_delegate_is_a_registered_tool_that_produces_a_tree_operation_request() -> None:
    registry = ToolRegistry((DelegateTool(_agents()),))
    result = asyncio.run(
        registry.execute(
            ToolCall(
                "delegate",
                DELEGATE_TOOL,
                {
                    "agent": "worker",
                    "instruction": "检查一个边界",
                },
            )
        )
    )

    assert result == DelegationRequest("worker", "检查一个边界")
    assert registry.definitions[0].name == DELEGATE_TOOL
    choices = registry.definitions[0].parameters["properties"]["agent"]["oneOf"]  # type: ignore[index]
    assert choices == [
        {"const": "root", "description": "总代理。"},
        {"const": "worker", "description": "通用执行者。"},
    ]


@pytest.mark.parametrize(
    "arguments",
    (
        {},
        {"agent": "worker", "instruction": ""},
        {"agent": "missing", "instruction": "x"},
    ),
)
def test_delegate_rejects_invalid_arguments_as_tool_output(arguments: dict[str, object]) -> None:
    result = asyncio.run(DelegateTool(_agents()).execute(ToolCall("delegate", DELEGATE_TOOL, arguments)))

    assert isinstance(result, ToolOutput)
    assert result.is_error is True


class FakeJournal:
    """实现 WorldJournal 协议的内存桩，只支持世界读取工具使用的查询。"""

    def __init__(self, commits: tuple[WorldCommit, ...] = (), activity: tuple[TreeActivity, ...] = ()) -> None:
        self.commits_by_scope = commits
        self.activity = activity
        self.queries: list[tuple[str, int, int]] = []

    async def initialize(self) -> None:
        raise NotImplementedError

    async def append_event(self, event: EnvironmentEvent) -> WorldCommit:
        raise NotImplementedError

    async def append_commits(self, inputs: tuple[WorldCommitInput, ...]) -> tuple[WorldCommit, ...]:
        raise NotImplementedError

    async def head(self, scopes: frozenset[str]) -> WorldFrontier:
        raise NotImplementedError

    async def delta(self, start: WorldFrontier, scopes: frozenset[str]) -> WorldDeltaPage:
        raise NotImplementedError

    async def commit(self, commit_id: str) -> WorldCommit | None:
        raise NotImplementedError

    async def commits(self, scope: str, after: int, limit: int) -> tuple[WorldCommit, ...]:
        self.queries.append((scope, after, limit))
        return tuple(item for item in self.commits_by_scope if item.scopes.get(scope, 0) > after)[:limit]

    async def tree_index(self, limit: int) -> tuple[TreeActivity, ...]:
        return self.activity[:limit]

    async def append_commit(
        self,
        *,
        commit_id: str,
        kind: str,
        source: str,
        summary: str,
        scopes: frozenset[str],
        based_on: WorldFrontier,
        data: Mapping[str, Any],
        occurred_at: datetime | None = None,
    ) -> WorldCommit:
        raise NotImplementedError


def _commit(commit_id: str, kind: str, scope: str, sequence: int, summary: str) -> WorldCommit:
    return WorldCommit(
        commit_id,
        kind,
        "test",
        summary,
        datetime.now(UTC),
        {scope: sequence},
        WorldFrontier(),
        {"payload": sequence},
    )


def test_world_read_returns_bodies_and_declares_observed_scope() -> None:
    journal = FakeJournal((_commit("c-1", "tool.succeeded", "scope", 1, "完成"),))
    tool = WorldReadTool(journal)

    scopes = tool.resolve_scopes(ToolCall("read", WORLD_READ_TOOL, {"scope": "scope"}))
    result = asyncio.run(tool.execute(ToolCall("read", WORLD_READ_TOOL, {"scope": "scope", "after": 0, "limit": 5})))

    assert scopes.observe == frozenset({"scope"})
    assert journal.queries == [("scope", 0, 5)]
    assert isinstance(result, ToolOutput) and result.is_error is False
    payload = json.loads(result.content)
    assert payload["count"] == 1
    assert payload["commits"][0]["commit_id"] == "c-1"
    assert payload["commits"][0]["data"] == {"payload": 1}
    assert payload["commits"][0]["summary"] == "完成"


def test_world_read_filters_kind_exactly_and_by_prefix() -> None:
    journal = FakeJournal(
        (
            _commit("c-1", "environment.message", "scope", 1, "外部消息"),
            _commit("c-2", "tool.succeeded", "scope", 2, "工具完成"),
        )
    )
    tool = WorldReadTool(journal)

    exact = asyncio.run(tool.execute(ToolCall("read", WORLD_READ_TOOL, {"scope": "scope", "kind": "tool.succeeded"})))
    prefix = asyncio.run(tool.execute(ToolCall("read", WORLD_READ_TOOL, {"scope": "scope", "kind": "environment.*"})))

    assert isinstance(exact, ToolOutput) and json.loads(exact.content)["commits"][0]["commit_id"] == "c-2"
    assert isinstance(prefix, ToolOutput) and json.loads(prefix.content)["commits"][0]["commit_id"] == "c-1"


@pytest.mark.parametrize(
    "arguments",
    (
        {},
        {"scope": ""},
        {"scope": "scope", "after": -1},
        {"scope": "scope", "limit": 0},
        {"scope": "scope", "limit": 101},
        {"scope": "scope", "kind": ""},
    ),
)
def test_world_read_rejects_invalid_arguments_as_tool_output(arguments: dict[str, object]) -> None:
    tool = WorldReadTool(FakeJournal())

    result = asyncio.run(tool.execute(ToolCall("read", WORLD_READ_TOOL, arguments)))

    assert isinstance(result, ToolOutput)
    assert result.is_error is True


def test_world_trees_lists_forest_index_and_limits() -> None:
    journal = FakeJournal(activity=(TreeActivity("a", 2, datetime.now(UTC), datetime.now(UTC)),))
    tool = WorldTreesTool(journal)

    scopes = tool.resolve_scopes(ToolCall("trees", WORLD_TREES_TOOL, {}))
    result = asyncio.run(tool.execute(ToolCall("trees", WORLD_TREES_TOOL, {"limit": 32})))
    too_many = asyncio.run(tool.execute(ToolCall("trees", WORLD_TREES_TOOL, {"limit": 257})))

    assert scopes.observe == frozenset()
    assert isinstance(result, ToolOutput) and result.is_error is False
    payload = json.loads(result.content)
    assert payload["count"] == 1
    assert payload["trees"][0]["tree_id"] == "a"
    assert payload["trees"][0]["commit_count"] == journal.activity[0].commit_count
    assert isinstance(too_many, ToolOutput) and too_many.is_error is True


def test_world_tools_are_registered_under_service_domain_ids() -> None:
    registry = ToolRegistry((WorldReadTool(FakeJournal()), WorldTreesTool(FakeJournal())))

    assert registry.names == frozenset({WORLD_READ_TOOL, WORLD_TREES_TOOL})
    assert [definition.name for definition in registry.definitions] == [WORLD_READ_TOOL, WORLD_TREES_TOOL]

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import pytest

from aurora_bot.agents import AgentCatalog
from aurora_bot.contracts import (
    AgentDefinition,
    DelegationRequest,
    EnvironmentEvent,
    ScopeCatalog,
    ScopeDeclaration,
    ScopeKind,
    ToolCall,
    ToolDefinition,
    ToolOutput,
    ToolStatus,
    TreeActivity,
    WorldCommit,
    WorldCommitInput,
    WorldDeltaPage,
    WorldFrontier,
    WorldStreamPage,
)
from aurora_bot.tools import (
    DELEGATE_TOOL,
    WAIT_TOOL,
    WORLD_READ_TOOL,
    WORLD_SCOPES_TOOL,
    WORLD_TREES_TOOL,
    DelegateTool,
    ToolRegistrationError,
    ToolRegistry,
    WaitTool,
    WorldReadTool,
    WorldTreesTool,
)
from aurora_bot.tools.builtin import builtin_tools
from tests.support.tool import EchoTool

if TYPE_CHECKING:
    from collections.abc import Mapping


def _scope_catalog() -> ScopeCatalog:
    return ScopeCatalog(
        (
            ScopeDeclaration("aurora:world/console", ScopeKind.RESOURCE, "终端输入先进入的世界线"),
            ScopeDeclaration("aurora:run/*", ScopeKind.RUN, "一次运行的因果台账"),
        )
    )


class FailingTool(EchoTool):
    async def execute(self, call: ToolCall) -> ToolOutput:
        raise RuntimeError(str(call.arguments["error"]))


class UnknownTool(EchoTool):
    async def execute(self, call: ToolCall) -> ToolOutput:
        return ToolOutput(str(call.arguments["value"]), status=ToolStatus.UNKNOWN)


def _agents() -> AgentCatalog:
    return AgentCatalog(
        (
            AgentDefinition(
                "aurora:agent/definition/root",
                "总代理。",
                "aurora:prompt/agent/root",
                "test:ai/endpoint/quality",
                frozenset({DELEGATE_TOOL}),
                frozenset({"aurora:agent/definition/worker"}),
            ),
            AgentDefinition(
                "aurora:agent/definition/worker",
                "通用执行者。",
                "aurora:prompt/agent/worker",
                "test:ai/endpoint/fast",
                frozenset(),
                frozenset(),
            ),
        )
    )


def test_registry_forms_sorted_immutable_catalog_and_filters_visibility() -> None:
    registry = ToolRegistry((EchoTool(), DelegateTool(_agents())))

    assert registry.names == frozenset({DELEGATE_TOOL, "test:tool/definition/echo"})
    assert [definition.name for definition in registry.definitions] == [DELEGATE_TOOL, "test:tool/definition/echo"]
    assert [definition.name for definition in registry.definitions_for(frozenset({"test:tool/definition/echo"}))] == [
        "test:tool/definition/echo"
    ]


def test_registry_rejects_non_domain_and_duplicate_tool_ids() -> None:
    class InvalidTool(EchoTool):
        @property
        def definition(self) -> ToolDefinition:
            return ToolDefinition("echo", "无效名称。", {})

    with pytest.raises(ValueError, match="工具身份"):
        ToolRegistry((InvalidTool(),))
    with pytest.raises(ToolRegistrationError, match="重复注册"):
        ToolRegistry((EchoTool(), EchoTool()))


def test_registry_accepts_uppercase_mcp_raw_name_but_keeps_framework_ids_lowercase() -> None:
    class McpCamelTool(EchoTool):
        @property
        def definition(self) -> ToolDefinition:
            return ToolDefinition("com.github.windows_mcp:tool/definition/Screenshot", "第三方大写工具名。", {})

    class WrongSpeciesTool(EchoTool):
        @property
        def definition(self) -> ToolDefinition:
            return ToolDefinition("aurora:agent/definition/delegate", "路径不在 tool/ 下的 ID 不是工具。", {})

    registry = ToolRegistry((McpCamelTool(),))
    assert "com.github.windows_mcp:tool/definition/Screenshot" in registry.names
    assert "com.github.windows_mcp:tool/definition/Screenshot" in [d.name for d in registry.definitions]
    with pytest.raises(ValueError, match="工具身份"):
        ToolRegistry((WrongSpeciesTool(),))


def test_registry_routes_calls_and_normalizes_boundary_failures() -> None:
    with pytest.raises(ToolRegistrationError, match="重复注册"):
        ToolRegistry((EchoTool(), FailingTool()))

    echo = asyncio.run(
        ToolRegistry((EchoTool(),)).execute(ToolCall("echo", "test:tool/definition/echo", {"value": "ok"}))
    )
    missing = asyncio.run(ToolRegistry().execute(ToolCall("missing", "test:tool/definition/missing", {})))
    failed = asyncio.run(
        ToolRegistry((FailingTool(),)).execute(ToolCall("failed", "test:tool/definition/echo", {"error": "broken"}))
    )
    unknown = asyncio.run(
        ToolRegistry((UnknownTool(),)).execute(ToolCall("unknown", "test:tool/definition/echo", {"value": "uncertain"}))
    )

    assert echo == ToolOutput("ok")
    assert missing == ToolOutput("未知工具：test:tool/definition/missing", status=ToolStatus.FAILED)
    assert failed == ToolOutput("工具执行失败：broken", status=ToolStatus.FAILED)
    assert unknown == ToolOutput("uncertain", status=ToolStatus.UNKNOWN)


def test_delegate_is_a_registered_tool_that_produces_a_tree_operation_request() -> None:
    registry = ToolRegistry((DelegateTool(_agents()),))
    result = asyncio.run(
        registry.execute(
            ToolCall(
                "delegate",
                DELEGATE_TOOL,
                {
                    "agent": "aurora:agent/definition/worker",
                    "instruction": "检查一个边界",
                },
            )
        )
    )

    assert result == DelegationRequest("aurora:agent/definition/worker", "检查一个边界")
    assert registry.definitions[0].name == DELEGATE_TOOL
    choices = registry.definitions[0].parameters["properties"]["agent"]["oneOf"]  # type: ignore[index]
    assert choices == (
        {"const": "aurora:agent/definition/root", "description": "总代理。"},
        {"const": "aurora:agent/definition/worker", "description": "通用执行者。"},
    )


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
    assert result.status is ToolStatus.FAILED
    assert result.is_error is True


class FakeJournal:
    """实现 WorldJournal 协议的内存桩，只支持世界读取工具使用的查询。"""

    def __init__(self, commits: tuple[WorldCommit, ...] = (), activity: tuple[TreeActivity, ...] = ()) -> None:
        self.commits_by_scope = commits
        self.activity = activity
        self.queries: list[tuple[str, int, int]] = []

    async def initialize(self) -> None:
        raise NotImplementedError

    async def cursor(self) -> int:
        raise NotImplementedError

    async def active_scopes(self, since: datetime) -> tuple[str, ...]:
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

    async def stream(self, after: int, limit: int) -> WorldStreamPage:
        raise NotImplementedError

    async def close(self) -> None:
        return None

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
    assert result.status is ToolStatus.FAILED
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


def test_wait_tool_sleeps_within_bounds_and_rejects_invalid_values() -> None:
    tool = WaitTool()

    started = asyncio.run(tool.execute(ToolCall("wait", WAIT_TOOL, {})))
    invalid = asyncio.run(tool.execute(ToolCall("wait", WAIT_TOOL, {"seconds": -1})))
    too_long = asyncio.run(tool.execute(ToolCall("wait", WAIT_TOOL, {"seconds": 61})))

    assert isinstance(started, ToolOutput) and "已等待" in started.content
    assert isinstance(invalid, ToolOutput) and invalid.is_error is True
    assert isinstance(too_long, ToolOutput) and too_long.is_error is True


def test_builtin_tools_form_the_default_catalog_before_external_tools() -> None:
    journal = FakeJournal()
    builtins = builtin_tools(agents=_agents(), journal=journal, scopes=_scope_catalog())
    registry = ToolRegistry((*builtins, EchoTool()))

    assert registry.names == frozenset(
        {DELEGATE_TOOL, WAIT_TOOL, WORLD_READ_TOOL, WORLD_SCOPES_TOOL, WORLD_TREES_TOOL, "test:tool/definition/echo"}
    )


def test_world_tools_are_registered_under_service_domain_ids() -> None:
    registry = ToolRegistry((WorldReadTool(FakeJournal()), WorldTreesTool(FakeJournal())))

    assert registry.names == frozenset({WORLD_READ_TOOL, WORLD_TREES_TOOL})
    assert [definition.name for definition in registry.definitions] == [WORLD_READ_TOOL, WORLD_TREES_TOOL]

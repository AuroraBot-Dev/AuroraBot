from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from src.agents import AgentCatalog
from src.contracts import (
    AgentDefinition,
    AgentStatus,
    AgentTree,
    ChatMessage,
    EnvironmentEvent,
    Model,
    ModelRequest,
    Tool,
    ToolCall,
    ToolDefinition,
    ToolOutput,
    ToolScopes,
    TreeActivity,
    TreeStatus,
    WorldFrontier,
    WorldJournal,
)
from src.engine import AgentTreeRunner
from src.prompt import PromptAssembler, PromptCatalog
from src.tools import DELEGATE_TOOL, WORLD_READ_TOOL, DelegateTool, ToolRegistry, WorldReadTool
from src.world import SqlAlchemyWorldJournal

if TYPE_CHECKING:
    from pathlib import Path

EXPECTED_DELEGATION_NODES = 2
_SECOND_REQUEST = 2
_EXPECTED_SCOPE_SEQUENCE = 5


@dataclass(slots=True)
class FakeModel:
    responses: list[ChatMessage]
    requests: list[ModelRequest] = field(default_factory=list)

    async def complete(self, request: ModelRequest) -> ChatMessage:
        self.requests.append(request)
        return self.responses.pop(0)


class EchoTool:
    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            "aur.test.echo",
            "Echo one value.",
            {"type": "object", "properties": {"value": {"type": "string"}}, "required": ["value"]},
        )

    async def execute(self, call: ToolCall) -> ToolOutput:
        return ToolOutput(str(call.arguments["value"]))


class FailingTool(EchoTool):
    async def execute(self, call: ToolCall) -> ToolOutput:
        raise RuntimeError(str(call.arguments.get("error", "broken")))


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
class EventInjectingModel:
    responses: list[ChatMessage]
    journal: SqlAlchemyWorldJournal
    event: EnvironmentEvent
    requests: list[ModelRequest] = field(default_factory=list)

    async def complete(self, request: ModelRequest) -> ChatMessage:
        self.requests.append(request)
        if len(self.requests) == _SECOND_REQUEST:
            await self.journal.append_event(self.event)
        return self.responses.pop(0)


def _assembler() -> PromptAssembler:
    return PromptAssembler(
        PromptCatalog(
            ("You are Aurora.",),
            {"root": "Solve the whole task.", "worker": "Solve only the assigned part."},
        )
    )


def _agent(
    definition_id: str = "root",
    prompt: str = "root",
    model: str = "model",
    tools: frozenset[str] = frozenset(),
    children: frozenset[str] = frozenset(),
) -> AgentDefinition:
    return AgentDefinition(definition_id, f"{definition_id} Agent.", prompt, model, tools, children)


def _runner(
    model: Model,
    definitions: tuple[AgentDefinition, ...],
    *tools: Tool,
    world: WorldJournal | None = None,
) -> AgentTreeRunner:
    agents = AgentCatalog(definitions)
    registry = ToolRegistry((DelegateTool(agents), *tools))
    return AgentTreeRunner(model, _assembler(), agents, registry, world=world)


def test_root_completes_one_message_assistant_loop() -> None:
    model = FakeModel([ChatMessage.assistant("done")])
    root = _agent(model="root-model")
    tree = AgentTree.create("tree", "root", root, "hello")

    result = asyncio.run(_runner(model, (root,)).run(tree))

    assert result.status == TreeStatus.COMPLETED
    assert result.node("root").result == "done"
    assert model.requests[0].model == "root-model"
    assert [message.role for message in model.requests[0].messages] == ["system", "message"]
    assert model.requests[0].tools == ()


def test_runner_publishes_each_immutable_tree_transition() -> None:
    model = FakeModel([ChatMessage.assistant("done")])
    root = _agent(model="root-model")
    tree = AgentTree.create("tree", "root", root, "hello")
    snapshots: list[AgentTree] = []

    result = asyncio.run(_runner(model, (root,)).run(tree, observer=snapshots.append))

    assert [snapshot.status for snapshot in snapshots] == [
        TreeStatus.RUNNING,
        TreeStatus.RUNNING,
        TreeStatus.COMPLETED,
    ]
    assert snapshots[0] is tree
    assert snapshots[-1] is result


def test_tool_result_returns_to_same_node_before_final_assistant() -> None:
    model = FakeModel(
        [
            ChatMessage.assistant(tool_calls=(ToolCall("echo-1", "aur.test.echo", {"value": "hello"}),)),
            ChatMessage.assistant("finished"),
        ]
    )
    root = _agent(model="tool-model", tools=frozenset({"aur.test.echo"}))
    tree = AgentTree.create("tree", "root", root, "echo")

    result = asyncio.run(_runner(model, (root,), EchoTool()).run(tree))

    assert result.status == TreeStatus.COMPLETED
    assert [message.role for message in result.node("root").messages] == [
        "message",
        "assistant",
        "tool",
        "assistant",
    ]
    assert result.node("root").messages[2].content == "hello"
    assert [tool.name for tool in model.requests[0].tools] == ["aur.test.echo"]


def test_delegate_creates_child_with_its_own_model_and_resumes_parent() -> None:
    delegate = ToolCall(
        "delegate-1",
        DELEGATE_TOOL,
        {"agent": "worker", "instruction": "inspect this"},
    )
    model = FakeModel(
        [
            ChatMessage.assistant(tool_calls=(delegate,)),
            ChatMessage.assistant("child result"),
            ChatMessage.assistant("root result"),
        ]
    )
    root = _agent(
        model="large-model",
        tools=frozenset({DELEGATE_TOOL}),
        children=frozenset({"worker"}),
    )
    worker = _agent("worker", "worker", "small-model")
    tree = AgentTree.create("tree", "root", root, "delegate work")

    result = asyncio.run(_runner(model, (root, worker)).run(tree))

    assert result.status == TreeStatus.COMPLETED
    assert len(result.nodes) == EXPECTED_DELEGATION_NODES
    child = result.nodes[1]
    assert child.parent_id == "root"
    assert child.definition_id == "worker"
    assert child.model == "small-model"
    assert child.status == AgentStatus.COMPLETED
    assert [request.model for request in model.requests] == ["large-model", "small-model", "large-model"]
    parent_tool = next(message for message in result.node("root").messages if message.role == "tool")
    assert parent_tool.tool_call_id == "delegate-1"
    assert parent_tool.content == "child result"


def test_tool_failure_is_a_tool_message_not_a_tree_failure() -> None:
    model = FakeModel(
        [
            ChatMessage.assistant(tool_calls=(ToolCall("missing-1", "aur.test.missing", {}),)),
            ChatMessage.assistant("recovered"),
        ]
    )
    root = _agent(tools=frozenset({"aur.test.missing"}))
    tree = AgentTree.create("tree", "root", root, "try")

    result = asyncio.run(_runner(model, (root,)).run(tree))

    assert result.status == TreeStatus.COMPLETED
    tool_message = result.node("root").messages[2]
    assert tool_message.role == "tool"
    assert tool_message.is_error is True
    assert tool_message.content == "未知工具：aur.test.missing"


def test_model_failure_becomes_tree_failure() -> None:
    class FailingModel:
        async def complete(self, request: ModelRequest) -> ChatMessage:
            raise RuntimeError(request.model)

    root = _agent()
    tree = AgentTree.create("tree", "root", root, "hello")
    result = asyncio.run(_runner(FailingModel(), (root,)).run(tree))

    assert result.status == TreeStatus.FAILED
    assert result.node("root").error == "model failed: model"


def test_tool_exception_and_hidden_tool_are_returned_to_model() -> None:
    model = FakeModel(
        [
            ChatMessage.assistant(tool_calls=(ToolCall("fail", "aur.test.echo", {"error": "broken"}),)),
            ChatMessage.assistant(tool_calls=(ToolCall("hidden", "aur.test.missing", {}),)),
            ChatMessage.assistant("recovered"),
        ]
    )
    root = _agent(tools=frozenset({"aur.test.echo"}))
    tree = AgentTree.create("tree", "root", root, "hello")

    result = asyncio.run(_runner(model, (root,), FailingTool()).run(tree))

    tools = [message for message in result.node("root").messages if message.role == "tool"]
    assert tools[0].content == "工具执行失败：broken"
    assert tools[1].content == "当前 Agent 不可见此工具：aur.test.missing"


def test_runner_rejects_invalid_limits() -> None:
    model = FakeModel([ChatMessage.assistant("done")])
    root = _agent()
    with pytest.raises(ValueError, match="limits"):
        agents = AgentCatalog((root,))
        AgentTreeRunner(model, _assembler(), agents, ToolRegistry((DelegateTool(agents),)), max_steps=0)


def test_runner_rejects_node_facts_that_do_not_match_predefined_agent() -> None:
    model = FakeModel([ChatMessage.assistant("done")])
    root = _agent(model="expected")
    tree = AgentTree.create("tree", "root", root, "hello")
    invalid = AgentTree(tree.tree_id, tree.root_id, (replace(tree.node("root"), model="other"),))

    with pytest.raises(ValueError, match="预定义原型不一致"):
        asyncio.run(_runner(model, (root,)).run(invalid))


def test_invalid_delegate_arguments_return_tool_error() -> None:
    model = FakeModel(
        [
            ChatMessage.assistant(tool_calls=(ToolCall("delegate-1", DELEGATE_TOOL, {}),)),
            ChatMessage.assistant("recovered"),
        ]
    )
    root = _agent(tools=frozenset({DELEGATE_TOOL}), children=frozenset({"worker"}))
    worker = _agent("worker", "worker")
    tree = AgentTree.create("tree", "root", root, "hello")

    result = asyncio.run(_runner(model, (root, worker)).run(tree))

    assert result.node("root").messages[2].is_error is True
    assert "委派参数无效" in result.node("root").messages[2].content


def test_delegate_rejects_registered_agent_outside_parent_allowlist() -> None:
    model = FakeModel(
        [
            ChatMessage.assistant(
                tool_calls=(ToolCall("delegate", DELEGATE_TOOL, {"agent": "worker", "instruction": "work"}),)
            ),
            ChatMessage.assistant("recovered"),
        ]
    )
    root = _agent(tools=frozenset({DELEGATE_TOOL}), children=frozenset({"reviewer"}))
    worker = _agent("worker", "worker")
    reviewer = _agent("reviewer", "worker")
    tree = AgentTree.create("tree", "root", root, "hello")

    result = asyncio.run(_runner(model, (root, worker, reviewer)).run(tree))

    assert len(result.nodes) == 1
    assert result.node("root").messages[2] == ChatMessage.tool(
        "delegate",
        "当前 Agent 不允许委派给：worker",
        is_error=True,
    )


def test_world_delta_defers_a_tool_batch_then_the_next_batch_seals_its_frontier(tmp_path: Path) -> None:
    async def scenario() -> tuple[AgentTree, ScopedEchoTool, tuple[str, ...]]:
        scope = "qq:group-1"
        journal = SqlAlchemyWorldJournal(tmp_path / "world.sqlite3")
        await journal.initialize()
        first = EnvironmentEvent("event-1", "qq", scope, "message", datetime.now(UTC), "第一条消息")
        await journal.append_event(first)
        frontier = await journal.head(frozenset({scope}))
        await journal.append_event(EnvironmentEvent("event-2", "qq", scope, "message", datetime.now(UTC), "第二条消息"))
        tool = ScopedEchoTool(scope)
        model = EventInjectingModel(
            [
                ChatMessage.assistant(
                    tool_calls=(
                        ToolCall("first-a", "aur.test.echo", {"value": "first-a"}),
                        ToolCall("first-b", "aur.test.echo", {"value": "first-b"}),
                    )
                ),
                ChatMessage.assistant(tool_calls=(ToolCall("second", "aur.test.echo", {"value": "second"}),)),
                ChatMessage.assistant("完成"),
            ],
            journal,
            EnvironmentEvent("event-3", "qq", scope, "message", datetime.now(UTC), "第三条消息"),
        )
        root = _agent(tools=frozenset({"aur.test.echo"}))
        tree = AgentTree.create("tree", "root", root, "开始", frontier)
        runner = _runner(model, (root,), tool, world=journal)
        result = await runner.run(tree)
        commits = await journal.delta(WorldFrontier(), frozenset({scope}))
        await journal.close()
        return result, tool, tuple(commit.kind for commit in commits.commits)

    result, tool, commits = asyncio.run(scenario())
    node = result.node("root")

    assert result.status == TreeStatus.COMPLETED
    assert tool.values == ["second"]
    assert node.messages[2].is_error is True
    assert '"kind":"world.delta"' in node.messages[2].content
    assert [node.messages[index].tool_call_id for index in (2, 3)] == ["first-a", "first-b"]
    assert node.observed_frontier.sequence("qq:group-1") == _EXPECTED_SCOPE_SEQUENCE
    assert commits == (
        "environment.message",
        "environment.message",
        "environment.message",
        "tool.requested",
        "tool.succeeded",
    )


def test_root_output_is_deferred_once_and_then_seals_the_observed_frontier(tmp_path: Path) -> None:
    async def scenario() -> tuple[AgentTree, EventInjectingModel]:
        scope = "qq:group-2"
        journal = SqlAlchemyWorldJournal(tmp_path / "world.sqlite3")
        await journal.initialize()
        await journal.append_event(EnvironmentEvent("event-1", "qq", scope, "message", datetime.now(UTC), "第一条"))
        frontier = await journal.head(frozenset({scope}))
        await journal.append_event(EnvironmentEvent("event-2", "qq", scope, "message", datetime.now(UTC), "第二条"))
        model = EventInjectingModel(
            [ChatMessage.assistant("草稿"), ChatMessage.assistant("最终回复")],
            journal,
            EnvironmentEvent("event-3", "qq", scope, "message", datetime.now(UTC), "第三条"),
        )
        root = _agent()
        tree = AgentTree.create("tree", "root", root, "开始", frontier)
        runner = _runner(model, (root,), world=journal)
        result = await runner.run(tree)
        await journal.close()
        return result, model

    result, model = asyncio.run(scenario())
    node = result.node("root")

    assert result.status == TreeStatus.COMPLETED
    assert node.result == "最终回复"
    assert [message.role for message in node.messages] == ["message", "assistant", "message", "assistant"]
    assert '"kind":"world.delta"' in node.messages[2].content
    assert len(model.requests) == _SECOND_REQUEST


def test_world_read_tool_returns_bodies_and_forest_indexes_the_tree(tmp_path: Path) -> None:
    async def scenario() -> tuple[AgentTree, tuple[str, ...], tuple[str, ...], tuple[TreeActivity, ...]]:
        scope = "qq:group-read-1"
        journal = SqlAlchemyWorldJournal(tmp_path / "world.sqlite3")
        await journal.initialize()
        await journal.append_event(EnvironmentEvent("event-1", "qq", scope, "message", datetime.now(UTC), "第一条消息"))
        frontier = await journal.head(frozenset({scope}))
        read_tool = WorldReadTool(journal)
        model = FakeModel(
            [
                ChatMessage.assistant(tool_calls=(ToolCall("read-1", WORLD_READ_TOOL, {"scope": scope, "after": 0}),)),
                ChatMessage.assistant("完成"),
            ]
        )
        root = _agent(tools=frozenset({WORLD_READ_TOOL}))
        tree = AgentTree.create("tree", "root", root, "看看世界", frontier)
        result = await _runner(model, (root,), read_tool, world=journal).run(tree)
        environment = await journal.delta(WorldFrontier(), frozenset({scope}))
        tree_scope = await journal.delta(WorldFrontier(), frozenset({"aurora:tree:tree"}))
        forest = await journal.tree_index(10)
        await journal.close()
        return (
            result,
            tuple(commit.kind for commit in environment.commits),
            tuple(commit.kind for commit in tree_scope.commits),
            forest,
        )

    result, environment, tree_scope, forest = asyncio.run(scenario())
    node = result.node("root")

    assert result.status == TreeStatus.COMPLETED
    assert [message.role for message in node.messages] == ["message", "assistant", "tool", "assistant"]
    body = json.loads(node.messages[2].content)
    assert body["count"] == 1
    assert body["commits"][0]["summary"] == "第一条消息"
    assert environment == ("environment.message",)
    assert tree_scope == (
        "engine.tree.started",
        "engine.model.requested",
        "engine.model.completed",
        "tool.requested",
        "tool.succeeded",
        "engine.model.requested",
        "engine.model.completed",
        "output.requested",
        "output.committed",
        "engine.tree.completed",
    )
    assert [(item.tree_id, item.commit_count) for item in forest] == [("tree", 10)]


def test_world_read_tool_first_batch_defers_until_delta_is_disclosed(tmp_path: Path) -> None:
    async def scenario() -> tuple[AgentTree, tuple[str, ...], tuple[str, ...]]:
        scope = "qq:group-read-2"
        journal = SqlAlchemyWorldJournal(tmp_path / "world.sqlite3")
        await journal.initialize()
        await journal.append_event(EnvironmentEvent("event-1", "qq", scope, "message", datetime.now(UTC), "第一条消息"))
        frontier = await journal.head(frozenset({scope}))
        await journal.append_event(EnvironmentEvent("event-2", "qq", scope, "message", datetime.now(UTC), "第二条消息"))
        read_tool = WorldReadTool(journal)
        model = FakeModel(
            [
                ChatMessage.assistant(tool_calls=(ToolCall("read-1", WORLD_READ_TOOL, {"scope": scope, "after": 0}),)),
                ChatMessage.assistant(tool_calls=(ToolCall("read-2", WORLD_READ_TOOL, {"scope": scope, "after": 0}),)),
                ChatMessage.assistant("完成"),
            ]
        )
        root = _agent(tools=frozenset({WORLD_READ_TOOL}))
        tree = AgentTree.create("tree", "root", root, "看看世界", frontier)
        result = await _runner(model, (root,), read_tool, world=journal).run(tree)
        environment = await journal.delta(WorldFrontier(), frozenset({scope}))
        tree_scope = await journal.delta(WorldFrontier(), frozenset({"aurora:tree:tree"}))
        await journal.close()
        return (
            result,
            tuple(commit.kind for commit in environment.commits),
            tuple(commit.kind for commit in tree_scope.commits),
        )

    result, environment, tree_scope = asyncio.run(scenario())
    node = result.node("root")

    assert result.status == TreeStatus.COMPLETED
    assert node.messages[2].is_error is True
    assert '"kind":"world.delta"' in node.messages[2].content
    assert node.messages[3].role == "assistant"
    body = json.loads(node.messages[4].content)
    assert body["commits"][0]["summary"] == "第一条消息"
    assert body["commits"][1]["summary"] == "第二条消息"
    assert environment == ("environment.message", "environment.message")
    assert tree_scope == (
        "engine.tree.started",
        "engine.model.requested",
        "engine.model.completed",
        "engine.world.delta_delivered",
        "engine.model.requested",
        "engine.model.completed",
        "tool.requested",
        "tool.succeeded",
        "engine.model.requested",
        "engine.model.completed",
        "output.requested",
        "output.committed",
        "engine.tree.completed",
    )

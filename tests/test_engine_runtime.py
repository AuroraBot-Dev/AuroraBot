from __future__ import annotations

import asyncio
from dataclasses import dataclass, field, replace

import pytest

from src.agents import AgentCatalog
from src.contracts import (
    AgentDefinition,
    AgentStatus,
    AgentTree,
    ChatMessage,
    Model,
    ModelRequest,
    Tool,
    ToolCall,
    ToolDefinition,
    ToolOutput,
    TreeStatus,
)
from src.engine import AgentTreeRunner
from src.prompt import PromptAssembler, PromptCatalog
from src.tools import DELEGATE_TOOL, DelegateTool, ToolRegistry

EXPECTED_DELEGATION_NODES = 2


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


def _assembler() -> PromptAssembler:
    return PromptAssembler(
        PromptCatalog(
            ("You are Aurora.",),
            {"root": "Solve the whole task.", "worker": "Solve only the assigned part."},
        )
    )


def _agent(
    definition_id: str = "root",
    profile: str = "root",
    model: str = "model",
    tools: frozenset[str] = frozenset(),
    children: frozenset[str] = frozenset(),
) -> AgentDefinition:
    return AgentDefinition(definition_id, f"{definition_id} Agent.", profile, model, tools, children)


def _runner(model: Model, definitions: tuple[AgentDefinition, ...], *tools: Tool) -> AgentTreeRunner:
    agents = AgentCatalog(definitions)
    registry = ToolRegistry((DelegateTool(agents), *tools))
    return AgentTreeRunner(model, _assembler(), agents, registry)


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

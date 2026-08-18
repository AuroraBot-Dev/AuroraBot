from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import pytest

from src.contracts import (
    AgentStatus,
    AgentTree,
    ChatMessage,
    ModelRequest,
    ToolCall,
    ToolDefinition,
    ToolOutput,
    TreeStatus,
)
from src.engine import AgentTreeRunner
from src.prompt import PromptAssembler, PromptCatalog

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
            "echo",
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


def test_root_completes_one_message_assistant_loop() -> None:
    model = FakeModel([ChatMessage.assistant("done")])
    tree = AgentTree.create("tree", "root", "root", "root-model", "hello")

    result = asyncio.run(AgentTreeRunner(model, _assembler()).run(tree))

    assert result.status == TreeStatus.COMPLETED
    assert result.node("root").result == "done"
    assert model.requests[0].model == "root-model"
    assert [message.role for message in model.requests[0].messages] == ["system", "message"]
    assert model.requests[0].tools == ()


def test_tool_result_returns_to_same_node_before_final_assistant() -> None:
    model = FakeModel(
        [
            ChatMessage.assistant(tool_calls=(ToolCall("echo-1", "echo", {"value": "hello"}),)),
            ChatMessage.assistant("finished"),
        ]
    )
    tree = AgentTree.create("tree", "root", "root", "tool-model", "echo", tools=frozenset({"echo"}))

    result = asyncio.run(AgentTreeRunner(model, _assembler(), (EchoTool(),)).run(tree))

    assert result.status == TreeStatus.COMPLETED
    assert [message.role for message in result.node("root").messages] == [
        "message",
        "assistant",
        "tool",
        "assistant",
    ]
    assert result.node("root").messages[2].content == "hello"
    assert [tool.name for tool in model.requests[0].tools] == ["echo"]


def test_delegate_creates_child_with_its_own_model_and_resumes_parent() -> None:
    delegate = ToolCall(
        "delegate-1",
        "delegate",
        {"profile": "worker", "model": "small-model", "tools": [], "instruction": "inspect this"},
    )
    model = FakeModel(
        [
            ChatMessage.assistant(tool_calls=(delegate,)),
            ChatMessage.assistant("child result"),
            ChatMessage.assistant("root result"),
        ]
    )
    tree = AgentTree.create(
        "tree",
        "root",
        "root",
        "large-model",
        "delegate work",
        tools=frozenset({"delegate"}),
    )

    result = asyncio.run(AgentTreeRunner(model, _assembler()).run(tree))

    assert result.status == TreeStatus.COMPLETED
    assert len(result.nodes) == EXPECTED_DELEGATION_NODES
    child = result.nodes[1]
    assert child.parent_id == "root"
    assert child.model == "small-model"
    assert child.status == AgentStatus.COMPLETED
    assert [request.model for request in model.requests] == ["large-model", "small-model", "large-model"]
    parent_tool = next(message for message in result.node("root").messages if message.role == "tool")
    assert parent_tool.tool_call_id == "delegate-1"
    assert parent_tool.content == "child result"


def test_tool_failure_is_a_tool_message_not_a_tree_failure() -> None:
    model = FakeModel(
        [
            ChatMessage.assistant(tool_calls=(ToolCall("missing-1", "missing", {}),)),
            ChatMessage.assistant("recovered"),
        ]
    )
    tree = AgentTree.create("tree", "root", "root", "model", "try", tools=frozenset({"missing"}))

    result = asyncio.run(AgentTreeRunner(model, _assembler()).run(tree))

    assert result.status == TreeStatus.COMPLETED
    tool_message = result.node("root").messages[2]
    assert tool_message.role == "tool"
    assert tool_message.is_error is True
    assert tool_message.content == "unknown tool: missing"


def test_model_failure_becomes_tree_failure() -> None:
    class FailingModel:
        async def complete(self, request: ModelRequest) -> ChatMessage:
            raise RuntimeError(request.model)

    tree = AgentTree.create("tree", "root", "root", "model", "hello")
    result = asyncio.run(AgentTreeRunner(FailingModel(), _assembler()).run(tree))

    assert result.status == TreeStatus.FAILED
    assert result.node("root").error == "model failed: model"


def test_tool_exception_and_hidden_tool_are_returned_to_model() -> None:
    model = FakeModel(
        [
            ChatMessage.assistant(tool_calls=(ToolCall("fail", "echo", {"error": "broken"}),)),
            ChatMessage.assistant(tool_calls=(ToolCall("hidden", "missing", {}),)),
            ChatMessage.assistant("recovered"),
        ]
    )
    tree = AgentTree.create("tree", "root", "root", "model", "hello", tools=frozenset({"echo"}))

    result = asyncio.run(AgentTreeRunner(model, _assembler(), (FailingTool(),)).run(tree))

    tools = [message for message in result.node("root").messages if message.role == "tool"]
    assert tools[0].content == "tool failed: broken"
    assert tools[1].content == "tool is not visible to this Agent: missing"


def test_runner_rejects_invalid_limits_duplicate_and_reserved_tools() -> None:
    model = FakeModel([ChatMessage.assistant("done")])
    with pytest.raises(ValueError, match="limits"):
        AgentTreeRunner(model, _assembler(), max_steps=0)
    with pytest.raises(ValueError, match="unique"):
        AgentTreeRunner(model, _assembler(), (EchoTool(), EchoTool()))

    class DelegateTool(EchoTool):
        @property
        def definition(self) -> ToolDefinition:
            return ToolDefinition("delegate", "Invalid override.", {})

    with pytest.raises(ValueError, match="reserved"):
        AgentTreeRunner(model, _assembler(), (DelegateTool(),))


def test_invalid_delegate_arguments_return_tool_error() -> None:
    model = FakeModel(
        [
            ChatMessage.assistant(tool_calls=(ToolCall("delegate-1", "delegate", {}),)),
            ChatMessage.assistant("recovered"),
        ]
    )
    tree = AgentTree.create("tree", "root", "root", "model", "hello", tools=frozenset({"delegate"}))

    result = asyncio.run(AgentTreeRunner(model, _assembler()).run(tree))

    assert result.node("root").messages[2].is_error is True
    assert "requires non-empty profile" in result.node("root").messages[2].content

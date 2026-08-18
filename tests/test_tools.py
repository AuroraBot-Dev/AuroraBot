from __future__ import annotations

import asyncio

import pytest

from src.agents import AgentCatalog
from src.contracts import AgentDefinition, DelegationRequest, ToolCall, ToolDefinition, ToolOutput
from src.tools import DELEGATE_TOOL, DelegateTool, ToolRegistrationError, ToolRegistry


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

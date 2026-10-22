from __future__ import annotations

import asyncio

import pytest
from referencing.exceptions import Unresolvable

from aurora_agent import (
    Agent,
    CallStatus,
    ChatMessage,
    RunRequest,
    RunStatus,
    ToolCall,
    ToolContext,
    ToolDefinition,
    ToolOutput,
)
from tests.agent.support import EchoTool, ScriptedModel, echo_call


@pytest.mark.parametrize(
    "history",
    [
        (ChatMessage.system("非法系统消息"),),
        (ChatMessage.tool("missing", "没有对应调用"),),
        (ChatMessage.assistant(tool_calls=(echo_call(),)),),
        (ChatMessage.assistant(tool_calls=(echo_call(),)), ChatMessage.message("插入工具批次")),
    ],
)
def test_initial_history_rejects_unpaired_protocol(history: tuple[ChatMessage, ...]) -> None:
    with pytest.raises(ValueError):
        RunRequest("执行", history=history)


def test_tool_inputs_and_schema_are_detached_from_mutable_sources() -> None:
    arguments = {"text": ["原值"]}
    schema = {"type": "object", "required": ["text"]}
    call = ToolCall("one", "echo", arguments)
    definition = ToolDefinition("echo", "返回输入", schema)
    arguments["text"].append("变更")
    schema["required"] = []
    assert call.arguments["text"] == ("原值",)
    assert definition.parameters["required"] == ("text",)
    with pytest.raises(TypeError):
        call.arguments["text"][0] = "变更"


def test_unexpected_tool_exception_retains_unknown_effect_before_propagating() -> None:
    class BrokenTool(EchoTool):
        async def execute(self, call: ToolCall, context: ToolContext) -> ToolOutput:
            self.calls.append((call, context))
            raise ValueError("执行后发生内部错误")

    tool = BrokenTool()
    model = ScriptedModel(ChatMessage.assistant(tool_calls=(echo_call(),)))
    run = Agent(instructions="处理", model="fake", provider=model, tools=(tool,)).create(RunRequest("执行"))
    with pytest.raises(ValueError, match="内部错误"):
        asyncio.run(run.run())
    assert run.snapshot().status == RunStatus.FAILED
    assert run.snapshot().calls[0].status == CallStatus.UNKNOWN
    asyncio.run(run.run())
    assert len(tool.calls) == 1


def test_schema_references_are_local_and_cannot_retrieve_external_resources() -> None:
    class LocalTool(EchoTool):
        definition = ToolDefinition(
            "echo", "本地引用", {"$defs": {"input": {"type": "object"}}, "$ref": "#/$defs/input"}
        )

    local = LocalTool()
    model = ScriptedModel(ChatMessage.assistant(tool_calls=(echo_call(),)), ChatMessage.assistant("完成"))
    run = Agent(instructions="处理", model="fake", provider=model, tools=(local,)).create(RunRequest("执行"))
    assert asyncio.run(run.run()).status == RunStatus.COMPLETED
    assert len(local.calls) == 1

    class RemoteTool(EchoTool):
        definition = ToolDefinition("echo", "未提供的外部引用", {"$ref": "urn:unavailable:schema"})

    remote = RemoteTool()
    model = ScriptedModel(ChatMessage.assistant(tool_calls=(echo_call(),)))
    run = Agent(instructions="处理", model="fake", provider=model, tools=(remote,)).create(RunRequest("执行"))
    # Registry 不提供 retrieve，外部引用在本地解析时失败，不访问网络。
    with pytest.raises(Unresolvable):
        asyncio.run(run.run())
    assert run.snapshot().status == RunStatus.FAILED
    assert not remote.calls

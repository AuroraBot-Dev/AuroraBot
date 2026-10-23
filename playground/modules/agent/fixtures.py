"""独立 Agent 的共用离线替身；默认静默，预设场景可注入显示函数。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from aurora_agent import (
    ChatMessage,
    ModelResponse,
    ToolAction,
    ToolCall,
    ToolDecision,
    ToolDefinition,
    ToolEffectUnknownError,
    ToolOutput,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from aurora_agent import ModelRequest, RunSnapshot, ToolContext


def quiet(message: str) -> None:
    pass


@dataclass
class Gate:
    """通过进入与释放信号演示并发，不依靠计时。"""

    entered: asyncio.Event = field(default_factory=asyncio.Event)
    release: asyncio.Event = field(default_factory=asyncio.Event)

    async def wait(self) -> None:
        self.entered.set()
        await self.release.wait()


class DemoModel:
    def __init__(
        self,
        *,
        gate: Gate | None = None,
        answer_only: bool = False,
        trace: Callable[[str], None] = quiet,
    ) -> None:
        self.gate = gate
        self.answer_only = answer_only
        self.trace = trace
        self.requests: list[ModelRequest] = []

    async def complete(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        round_number = len(self.requests)
        self.trace(f"  模型第 {round_number} 轮 · {request.model}")
        self.trace("  可见消息顺序：" + " → ".join(message.role for message in request.messages))
        inputs = [message.content for message in request.messages if message.role == "message"]
        self.trace(f"  可见输入：{inputs}")
        if round_number == 1 and self.gate is not None:
            await self.gate.wait()
        if round_number == 1 and not self.answer_only:
            calls = (
                ToolCall("echo-1", "echo", {"text": "第一项事实"}),
                ToolCall("echo-2", "echo", {"text": "第二项事实"}),
            )
            self.trace("  模型提出两个工具调用。")
            return ModelResponse(ChatMessage.assistant(tool_calls=calls))
        outputs = [message.content for message in request.messages if message.role == "tool"]
        content = f"第 {round_number} 轮回答：收到 {len(inputs)} 条输入；最新输入：{inputs[-1]}"
        if outputs:
            content += "；工具反馈：" + " / ".join(outputs)
        return ModelResponse(ChatMessage.assistant(content))


class EchoTool:
    definition = ToolDefinition(
        "echo",
        "返回本地示例文本",
        {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
            "additionalProperties": False,
        },
    )

    def __init__(
        self, *, gate: Gate | None = None, unknown: bool = False, trace: Callable[[str], None] = quiet
    ) -> None:
        self.gate = gate
        self.unknown = unknown
        self.trace = trace
        self.executed: list[str] = []

    async def execute(self, call: ToolCall, context: ToolContext) -> ToolOutput:
        self.executed.append(call.call_id)
        self.trace(f"  工具开始：run={context.run_id}, call={context.call_id}")
        if len(self.executed) == 1 and self.gate is not None:
            await self.gate.wait()
        if self.unknown:
            self.trace("  模拟效果已发出、回执未确认。")
            raise ToolEffectUnknownError("示例效果待核对")
        return ToolOutput(str(call.arguments["text"]))


class ReconsiderPolicy:
    def __init__(self, *, trace: Callable[[str], None] = quiet) -> None:
        self.trace = trace

    async def before_tool(self, snapshot: RunSnapshot, call: ToolCall) -> ToolDecision:
        self.trace(f"  行动前策略：{snapshot.run_id}/{call.call_id} 需要重新判断。")
        return ToolDecision(ToolAction.RECONSIDER, "环境已有新信息，请根据这条反馈直接回答。")

"""复用的离线场景构造与替身，不依赖测试用例模块。"""

from __future__ import annotations

from aurora_bot.contracts import (
    ToolCall,
    ToolDefinition,
    ToolOutput,
)


class EchoTool:
    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition("test:tool/definition/echo", "回显一个值。", {"type": "object"})

    async def execute(self, call: ToolCall) -> ToolOutput:
        return ToolOutput(str(call.arguments["value"]))

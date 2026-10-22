from __future__ import annotations

from aurora_bot.contracts import ToolCall, ToolDefinition, ToolOutput, ToolScopes, ToolStatus


class RecordingTool:
    definition = ToolDefinition(
        "test:tool/definition/echo",
        "回声",
        {"type": "object", "properties": {"value": {"type": "string"}}, "required": ["value"]},
    )

    def __init__(self, status: ToolStatus = ToolStatus.SUCCEEDED) -> None:
        self.status = status
        self.calls: list[ToolCall] = []

    def resolve_scopes(self, call: ToolCall) -> ToolScopes:
        return ToolScopes(observe=frozenset({"test:world/input"}), publish=frozenset({"test:world/output"}))

    async def execute(self, call: ToolCall) -> ToolOutput:
        self.calls.append(call)
        return ToolOutput(str(call.arguments["value"]), self.status)

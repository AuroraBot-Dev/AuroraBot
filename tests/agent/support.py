"""独立 Agent 的离线模型与工具替身。"""

from __future__ import annotations

from aurora_agent import ChatMessage, ModelRequest, ModelResponse, ToolCall, ToolContext, ToolDefinition, ToolOutput


class ScriptedModel:
    def __init__(self, *responses: ChatMessage | ModelResponse) -> None:
        self.responses = list(responses)
        self.requests: list[ModelRequest] = []

    async def complete(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        response = self.responses.pop(0)
        return response if isinstance(response, ModelResponse) else ModelResponse(response)


class EchoTool:
    definition = ToolDefinition(
        "echo",
        "返回输入文本",
        {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
            "additionalProperties": False,
        },
    )

    def __init__(self) -> None:
        self.calls: list[tuple[ToolCall, ToolContext]] = []

    async def execute(self, call: ToolCall, context: ToolContext) -> ToolOutput:
        self.calls.append((call, context))
        return ToolOutput(str(call.arguments["text"]))


def echo_call(call_id: str = "call-1", text: str = "事实") -> ToolCall:
    return ToolCall(call_id, "echo", {"text": text})

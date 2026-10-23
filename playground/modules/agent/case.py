"""可携带的离线依赖配置；替换的是外部端口，不是 Agent 执行器。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from jsonschema import Draft202012Validator, SchemaError
from pydantic import Field, model_validator

from aurora_agent import (
    ChatMessage,
    ModelError,
    ModelResponse,
    RunLimits,
    ToolAction,
    ToolCall,
    ToolDecision,
    ToolDefinition,
    ToolEffectUnknownError,
    ToolExecutionError,
    ToolOutput,
    Usage,
)
from playground.protocol import Model

if TYPE_CHECKING:
    from aurora_agent import ModelRequest, RunSnapshot, ToolContext


class CallInput(Model):
    call_id: str = Field(pattern=r"\S")
    name: str = Field(pattern=r"\S")
    arguments: dict[str, Any] = Field(default_factory=dict)

    def build(self) -> ToolCall:
        return ToolCall(self.call_id, self.name, self.arguments)


class Reply(Model):
    content: str = ""
    tool_calls: list[CallInput] = Field(default_factory=list)
    error: bool = False
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)


class Outcome(Model):
    effect: Literal["success", "error", "unknown"] = "success"
    content: str = ""
    is_error: bool = False


class ToolSpec(Model):
    name: str = Field(pattern=r"\S")
    description: str = Field(default="离线工具", pattern=r"\S")
    parameters: dict[str, Any] = Field(default_factory=lambda: {"type": "object", "properties": {}})
    outcomes: list[Outcome] = Field(min_length=1)

    @model_validator(mode="after")
    def check_schema(self) -> ToolSpec:
        try:
            Draft202012Validator.check_schema(self.parameters)
        except SchemaError as error:
            raise ValueError("工具参数必须是有效的 JSON Schema") from error
        return self


class Decision(Model):
    action: Literal["allow", "deny", "reconsider"] = "allow"
    content: str = ""

    @model_validator(mode="after")
    def check_content(self) -> Decision:
        if self.action != "allow" and not self.content.strip():
            raise ValueError("拒绝或重新判断需要说明")
        return self


class Case(Model):
    """用例只含 JSON 数据；不加载 Python 路径、个人配置或真实工具。"""

    version: Literal["aurora.agent.case/v1"] = "aurora.agent.case/v1"
    instructions: str = Field(default="依据输入完成任务。", pattern=r"\S")
    model: str = Field(default="script/local", pattern=r"\S")
    message: str = Field(pattern=r"\S")
    replies: list[Reply] = Field(min_length=1)
    tools: list[ToolSpec] = Field(default_factory=list)
    decisions: list[Decision] = Field(default_factory=list)
    max_model_calls: int = Field(default=32, ge=1)
    max_tool_calls: int = Field(default=128, ge=0)
    max_context_chars: int = Field(default=100_000, ge=1)

    @model_validator(mode="after")
    def unique_tools(self) -> Case:
        names = [tool.name for tool in self.tools]
        if len(names) != len(set(names)):
            raise ValueError("工具不能重名")
        return self

    def limits(self) -> RunLimits:
        return RunLimits(self.max_model_calls, self.max_tool_calls, self.max_context_chars)


class ScriptedModel:
    def __init__(self, replies: list[Reply]) -> None:
        self._replies = iter(replies)

    async def complete(self, request: ModelRequest) -> ModelResponse:
        reply = next(self._replies, None)
        if reply is None or reply.error:
            raise ModelError("离线模型响应耗尽或配置为失败")
        return ModelResponse(
            ChatMessage.assistant(reply.content, tool_calls=tuple(call.build() for call in reply.tool_calls)),
            Usage(reply.input_tokens, reply.output_tokens),
        )


class ScriptedTool:
    def __init__(self, spec: ToolSpec) -> None:
        self.definition = ToolDefinition(spec.name, spec.description, spec.parameters)
        self._outcomes = iter(spec.outcomes)

    async def execute(self, call: ToolCall, context: ToolContext) -> ToolOutput:
        outcome = next(self._outcomes, None)
        if outcome is None or outcome.effect == "error":
            raise ToolExecutionError("离线工具回执耗尽或配置为失败")
        if outcome.effect == "unknown":
            raise ToolEffectUnknownError("离线工具效果未知")
        return ToolOutput(outcome.content, is_error=outcome.is_error)


class ScriptedPolicy:
    def __init__(self, decisions: list[Decision]) -> None:
        self._decisions = iter(decisions)

    async def before_tool(self, snapshot: RunSnapshot, call: ToolCall) -> ToolDecision:
        decision = next(self._decisions, Decision())
        return ToolDecision(ToolAction(decision.action), decision.content)

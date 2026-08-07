"""协议中立模型网关契约。"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any, Final, Literal, Protocol


class _Msg(StrEnum):
    """本文件内所有用户可见或日志输出的字符串常量。"""

    INVALID_PERSISTED_MODEL_REQUEST = "invalid persisted model request"
    INVALID_PERSISTED_MODEL_RESULT = "invalid persisted model result"
    INVALID_CONTINUATION_CHANNEL = "invalid continuation channel"
    INVALID_MODEL_CONTINUATION = "invalid model continuation"


STRUCTURED_OUTPUT_NAME: Final = "aurora_result"

# 模式、重试策略、取消策略、工具选择字面量类型
ResponseMode = Literal["normalized", "native"]
RetryPolicy = Literal["none"]
CancelPolicy = Literal["never"]
ToolChoice = Literal["auto", "none", "required"]


@dataclass(frozen=True, slots=True)
class ModelMessage:
    """标准模型消息：角色和内容。

    ModelMessage object::

        {
            "role": "string",
            "content": "string"
        }

    """

    role: str
    content: str


@dataclass(frozen=True, slots=True)
class ModelBudget:
    """模型调用预算：最大输出 token、超时和可选成本上限。

    ModelBudget object::

        {
            "max_output_tokens": 1024,
            "timeout_seconds": 30.0,
            "max_cost_usd": 1.0 | null
        }

    """

    max_output_tokens: int = 1024
    timeout_seconds: float = 30.0
    max_cost_usd: float | None = None


@dataclass(frozen=True, slots=True)
class ModelRequest:
    """完整的模型请求：角色、消息列表、能力需求、预算、工具和延续状态。

    ModelRequest object::

        {
            "role": "string",
            "messages": [ModelMessage, ...],
            "required_capabilities": ["chat", ...],
            "response_mode": "normalized" | "native",
            "output_schema": {"...": "..."} | null,
            "allow_json_text_fallback": true,
            "invalid_output_result": {"...": "..."} | null,
            "budget": ModelBudget,
            "retry_policy": "none",
            "tools": [ToolDefinition, ...],
            "tool_choice": "auto" | "none" | "required",
            "parallel_tool_calls": false,
            "continuation": ModelContinuation | null,
            "cancel_policy": "never",
            "parameters": {"...": "..."}
        }

    """

    role: str
    messages: tuple[ModelMessage, ...]
    required_capabilities: frozenset[str] = frozenset({"chat"})
    response_mode: ResponseMode = "normalized"
    output_schema: dict[str, Any] | None = None
    allow_json_text_fallback: bool = True
    invalid_output_result: dict[str, Any] | None = None
    budget: ModelBudget = field(default_factory=ModelBudget)
    retry_policy: RetryPolicy = "none"
    tools: tuple["ToolDefinition", ...] = ()
    tool_choice: ToolChoice = "auto"
    parallel_tool_calls: bool = False
    continuation: "ModelContinuation | None" = None
    cancel_policy: CancelPolicy = "never"
    parameters: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["required_capabilities"] = sorted(self.required_capabilities)
        return value

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ModelRequest":
        """从持久化字典反序列化为 ModelRequest。"""
        budget_raw = value.get("budget", {})
        messages_raw = value.get("messages", [])
        tools_raw = value.get("tools", [])
        continuation_raw = value.get("continuation")
        if (
            not isinstance(budget_raw, dict)
            or not isinstance(messages_raw, (list, tuple))
            or not isinstance(tools_raw, (list, tuple))
        ):
            raise ValueError(_Msg.INVALID_PERSISTED_MODEL_REQUEST)
        return cls(
            role=str(value["role"]),
            messages=tuple(ModelMessage(str(item["role"]), str(item["content"])) for item in messages_raw),
            required_capabilities=frozenset(str(item) for item in value.get("required_capabilities", ["chat"])),
            response_mode=value.get("response_mode", "normalized"),
            output_schema=value.get("output_schema"),
            allow_json_text_fallback=bool(value.get("allow_json_text_fallback", True)),
            invalid_output_result=value.get("invalid_output_result"),
            budget=ModelBudget(**budget_raw),
            retry_policy=value.get("retry_policy", "none"),
            tools=tuple(
                ToolDefinition(str(item["name"]), str(item.get("description", "")), dict(item["parameters_schema"]))
                for item in tools_raw
            ),
            tool_choice=value.get("tool_choice", "auto"),
            parallel_tool_calls=bool(value.get("parallel_tool_calls", False)),
            continuation=ModelContinuation.from_dict(continuation_raw) if isinstance(continuation_raw, dict) else None,
            cancel_policy=value.get("cancel_policy", "never"),
            parameters=dict(value.get("parameters", {})),
        )


@dataclass(frozen=True, slots=True)
class ModelUsage:
    """模型用量统计：输入和输出 token 数。

    ModelUsage object::

        {
            "prompt_tokens": 0,
            "completion_tokens": 0
        }

    """

    prompt_tokens: int = 0
    completion_tokens: int = 0


@dataclass(frozen=True, slots=True)
class ModelResult:
    """模型调用结果：模型标识、协商能力、响应文本、用量、成本和工具调用。

    ModelResult object::

        {
            "model": "string",
            "negotiated_capabilities": ["chat", ...],
            "response_mode": "normalized" | "native",
            "text": "string",
            "data": {"...": "..."} | null,
            "usage": ModelUsage,
            "cost_usd": 0.0,
            "diagnostics": ["string", ...],
            "tool_calls": [ToolCall, ...],
            "finish_reason": "stop",
            "continuation": ModelContinuation | null
        }

    """

    model: str
    negotiated_capabilities: frozenset[str]
    response_mode: ResponseMode
    text: str
    data: dict[str, Any] | None
    usage: ModelUsage
    cost_usd: float
    diagnostics: tuple[str, ...] = ()
    tool_calls: tuple["ToolCall", ...] = ()
    finish_reason: str = "stop"
    continuation: "ModelContinuation | None" = None

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["negotiated_capabilities"] = sorted(self.negotiated_capabilities)
        return value

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ModelResult":
        """从持久化字典反序列化为 ModelResult。"""
        usage = value.get("usage", {})
        calls = value.get("tool_calls", [])
        continuation = value.get("continuation")
        if not isinstance(usage, dict) or not isinstance(calls, (list, tuple)):
            raise ValueError(_Msg.INVALID_PERSISTED_MODEL_RESULT)
        return cls(
            model=str(value["model"]),
            negotiated_capabilities=frozenset(str(item) for item in value.get("negotiated_capabilities", [])),
            response_mode=value.get("response_mode", "normalized"),
            text=str(value.get("text", "")),
            data=value.get("data"),
            usage=ModelUsage(**usage),
            cost_usd=float(value.get("cost_usd", 0.0)),
            diagnostics=tuple(str(item) for item in value.get("diagnostics", [])),
            tool_calls=tuple(
                ToolCall(str(item["call_id"]), str(item["name"]), dict(item.get("arguments", {}))) for item in calls
            ),
            finish_reason=str(value.get("finish_reason", "stop")),
            continuation=ModelContinuation.from_dict(continuation) if isinstance(continuation, dict) else None,
        )


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    """工具定义：名称、描述和参数 JSON Schema。

    ToolDefinition object::

        {
            "name": "string",
            "description": "string",
            "parameters_schema": {"...": "..."}
        }

    """

    name: str
    description: str
    parameters_schema: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ToolCall:
    """模型发起的工具调用：调用 ID、工具名和参数。

    ToolCall object::

        {
            "call_id": "string",
            "name": "string",
            "arguments": {"...": "..."}
        }

    """

    call_id: str
    name: str
    arguments: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ToolResult:
    """工具执行结果：调用 ID、结果数据和错误标记。

    ToolResult object::

        {
            "call_id": "string",
            "result": {"...": "..."},
            "is_error": false
        }

    """

    call_id: str
    result: dict[str, Any]
    is_error: bool = False


@dataclass(frozen=True, slots=True)
class ModelContinuation:
    """可序列化的模型端点重放状态。

    ModelContinuation object::

        {
            "provider": "string",
            "channel": "chat_completions" | "responses",
            "items": [{"...": "..."}, ...]
        }

    """

    provider: str
    channel: Literal["chat_completions", "responses"]
    items: tuple[dict[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ModelContinuation":
        """从持久化字典反序列化，校验 channel 和 items 合法性。"""
        channel = value.get("channel")
        if channel not in {"chat_completions", "responses"}:
            raise ValueError(_Msg.INVALID_CONTINUATION_CHANNEL)
        provider = value.get("provider")
        items = value.get("items", [])
        valid_items = isinstance(items, (list, tuple)) and all(isinstance(item, dict) for item in items)
        if not isinstance(provider, str) or not valid_items:
            raise ValueError(_Msg.INVALID_MODEL_CONTINUATION)
        return cls(provider, channel, tuple(dict(item) for item in items))


def append_tool_result(
    continuation: ModelContinuation,
    call_id: str,
    result: object,
    *,
    is_error: bool,
) -> ModelContinuation:
    """将一条工具结果追加到延续状态中（按通道格式化）。"""
    serialized = json.dumps({"is_error": is_error, "result": result}, ensure_ascii=False, separators=(",", ":"))
    if continuation.channel == "responses":
        item = {"type": "function_call_output", "call_id": call_id, "output": serialized}
    else:
        item = {"role": "tool", "tool_call_id": call_id, "content": serialized}
    return ModelContinuation(continuation.provider, continuation.channel, (*continuation.items, item))


class ModelGatewayError(RuntimeError):
    """安全、可审计的模型能力或执行失败。"""


class ModelCapabilityError(ModelGatewayError):
    """选定的角色或 Provider 无法在调用前满足请求。"""


class ModelBudgetError(ModelGatewayError):
    """模型调用超出声明的成本预算。"""


class ModelProvider(Protocol):
    """engine 调用模型实现的标准端口。"""

    async def complete(self, request: ModelRequest) -> ModelResult: ...

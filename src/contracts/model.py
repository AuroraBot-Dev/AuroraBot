"""RFC 0005 定义的协议中立模型网关契约。"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

# 模式、重试策略、取消策略、工具选择字面量类型
ResponseMode = Literal["normalized", "native"]
RetryPolicy = Literal["none"]
CancelPolicy = Literal["never", "on_external_activity"]
ToolChoice = Literal["auto", "none", "required"]


@dataclass(frozen=True, slots=True)
class ModelMessage:
    """标准模型消息：角色和内容。"""

    role: str
    content: str


@dataclass(frozen=True, slots=True)
class ModelBudget:
    """模型调用预算：最大输出 token、超时和可选成本上限。"""

    max_output_tokens: int = 1024
    timeout_seconds: float = 30.0
    max_cost_usd: float | None = None


@dataclass(frozen=True, slots=True)
class ModelRequest:
    """完整的模型请求：角色、消息列表、能力需求、预算、工具和延续状态。"""

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
            raise ValueError("invalid persisted model request")
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
    """模型用量统计：输入和输出 token 数。"""

    prompt_tokens: int = 0
    completion_tokens: int = 0


@dataclass(frozen=True, slots=True)
class ModelResult:
    """模型调用结果：模型标识、协商能力、响应文本、用量、成本和工具调用。"""

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
            raise ValueError("invalid persisted model result")
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
    """工具定义：名称、描述和参数 JSON Schema。"""

    name: str
    description: str
    parameters_schema: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ToolCall:
    """模型发起的工具调用：调用 ID、工具名和参数。"""

    call_id: str
    name: str
    arguments: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ToolResult:
    call_id: str
    result: dict[str, Any]
    is_error: bool = False


@dataclass(frozen=True, slots=True)
class ModelContinuation:
    """Serializable replay state owned by one model endpoint."""

    provider: str
    channel: Literal["chat_completions", "responses"]
    items: tuple[dict[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ModelContinuation":
        channel = value.get("channel")
        if channel not in {"chat_completions", "responses"}:
            raise ValueError("invalid continuation channel")
        provider = value.get("provider")
        items = value.get("items", [])
        valid_items = isinstance(items, (list, tuple)) and all(isinstance(item, dict) for item in items)
        if not isinstance(provider, str) or not valid_items:
            raise ValueError("invalid model continuation")
        return cls(provider, channel, tuple(dict(item) for item in items))


def append_tool_result(
    continuation: ModelContinuation,
    call_id: str,
    result: object,
    *,
    is_error: bool,
) -> ModelContinuation:
    """Append one provider-neutral tool result using the continuation's replay shape."""
    serialized = json.dumps({"is_error": is_error, "result": result}, ensure_ascii=False, separators=(",", ":"))
    if continuation.channel == "responses":
        item = {"type": "function_call_output", "call_id": call_id, "output": serialized}
    else:
        item = {"role": "tool", "tool_call_id": call_id, "content": serialized}
    return ModelContinuation(continuation.provider, continuation.channel, (*continuation.items, item))


class ModelGatewayError(RuntimeError):
    """A safe, auditable model capability or execution failure."""


class ModelCapabilityError(ModelGatewayError):
    """The selected role or Provider cannot satisfy a request before invocation."""


class ModelBudgetError(ModelGatewayError):
    """A completed model call exceeded its declared cost budget."""

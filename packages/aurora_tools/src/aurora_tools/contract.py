"""可通过 ctx 传递的工具声明、调用与执行结果。"""

from typing import Literal, NotRequired, TypedDict

from aurora_core.json_data import JsonValue


class ToolDefinition(TypedDict):
    """工具名称、用途与参数描述；parameters 使用 JSON Schema 对象。"""

    name: str
    description: str
    parameters: dict[str, JsonValue]


class ToolCall(TypedDict):
    """完整工具请求；id 用于关联后续工具消息，arguments 不含 JSON 碎片。"""

    id: str
    name: str
    arguments: dict[str, JsonValue]


class ToolBatchRequest(TypedDict):
    """工具调用批次，turn_id 用于关联请求与结果。"""

    turn_id: str
    calls: list[ToolCall]


class ToolResult(TypedDict):
    """单次工具结果；取消及未执行也有明确状态。"""

    call_id: str
    name: str
    status: Literal["completed", "failed", "cancelled"]
    value: NotRequired[JsonValue]
    error: NotRequired[dict[str, str]]


class ToolBatchState(TypedDict):
    turn_id: str
    execution_id: str
    status: Literal["running", "completed", "failed", "cancelled"]
    results: list[ToolResult]

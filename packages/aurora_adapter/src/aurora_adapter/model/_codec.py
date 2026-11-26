"""Aurora JSON 契约与 LiteLLM 响应之间的窄边界；不实现供应商协议。"""

from copy import deepcopy
from typing import Any, cast

from aurora_core.json_data import decode_json, encode_json

from .contract import ChatRequest, ChatResponse, FinishReason, JsonValue, ModelProtocolError, ReasoningBlock, ToolCall
from .response import ResponseBuffer


def object_data(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        value = value.model_dump()
    if not isinstance(value, dict):
        raise ModelProtocolError("模型响应必须为对象")
    return value


def choice_data(value: Any, *, streaming: bool) -> dict[str, Any] | None:
    choices = object_data(value).get("choices")
    if streaming and choices == []:
        return None
    if not isinstance(choices, list) or len(choices) != 1:
        raise ModelProtocolError("模型响应必须包含唯一 choice")
    choice = object_data(choices[0])
    if choice.get("index", 0) != 0:
        raise ModelProtocolError("模型响应 choice 的 index 必须为 0")
    return choice


def text_data(value: Any) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ModelProtocolError("模型文本与工具增量必须为字符串")
    return value


def finish_reason(value: Any) -> FinishReason:
    if value not in ("stop", "tool_calls", "length", "content_filter"):
        raise ModelProtocolError("模型结束原因不受支持或缺失")
    return cast(FinishReason, value)


def tool_call(value: dict[str, Any]) -> ToolCall:
    if value.get("type", "function") != "function":
        raise ModelProtocolError("仅支持 function 工具调用")
    function = object_data(value.get("function"))
    call_id, name = value.get("id"), function.get("name")
    if not isinstance(call_id, str) or not call_id or not isinstance(name, str) or not name:
        raise ModelProtocolError("工具调用必须具有完整 id 与名称")
    arguments = function.get("arguments")
    if not isinstance(arguments, str):
        raise ModelProtocolError("工具参数必须为完整 JSON 字符串")
    try:
        decoded = decode_json(arguments)
    except (ValueError, TypeError, RecursionError):
        raise ModelProtocolError("工具参数不是有效的严格 JSON 对象") from None
    if not isinstance(decoded, dict):
        raise ModelProtocolError("工具参数必须为 JSON 对象")
    return {"id": call_id, "name": name, "arguments": cast(dict[str, JsonValue], decoded)}


def tool_parts(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ModelProtocolError("tool_calls 必须为列表")
    return [object_data(item) for item in value]


def thinking_blocks(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ModelProtocolError("thinking_blocks 必须为列表")
    blocks = [object_data(item) for item in value]
    for block in blocks:
        if block.get("type") == "thinking":
            if not isinstance(block.get("thinking", ""), str) or not isinstance(block.get("signature", ""), str):
                raise ModelProtocolError("思考块的文本和签名必须为字符串")
        elif block.get("type") == "redacted_thinking":
            if not isinstance(block.get("data"), str) or not block["data"]:
                raise ModelProtocolError("隐藏思考块缺少数据")
        else:
            raise ModelProtocolError("未知思考块类型")
    return blocks


def chat_payload(request: ChatRequest) -> dict[str, Any]:
    messages: list[dict[str, Any]] = []
    for message in deepcopy(request["messages"]):
        converted: dict[str, Any] = dict(message)
        if "tool_calls" in message:
            converted["tool_calls"] = [
                {
                    "id": call["id"],
                    "type": "function",
                    "function": {"name": call["name"], "arguments": encode_json(call["arguments"])},
                }
                for call in message["tool_calls"]
            ]
        messages.append(converted)
    payload: dict[str, Any] = {"messages": messages}
    tools = request.get("tools")
    if tools:
        payload["tools"] = [{"type": "function", "function": deepcopy(tool)} for tool in tools]
    return payload


def chat_response(value: Any) -> ChatResponse:
    choice = choice_data(value, streaming=False)
    assert choice is not None
    message = object_data(choice.get("message"))
    if message.get("function_call"):
        raise ModelProtocolError("不支持旧式 function_call 响应")
    buffer = ResponseBuffer()
    buffer.append({"type": "text", "text": text_data(message.get("content"))})
    buffer.append({"type": "reasoning", "text": text_data(message.get("reasoning_content"))})
    for block in thinking_blocks(message.get("thinking_blocks")):
        if block["type"] == "thinking" and not block.get("signature"):
            raise ModelProtocolError("完整思考块缺少回传签名")
        buffer.append({"type": "thinking_block", "block": cast(ReasoningBlock, block)})
    for call in tool_parts(message.get("tool_calls")):
        buffer.append({"type": "tool_call", "tool_call": tool_call(call)})
    buffer.append({"type": "finish", "reason": finish_reason(choice.get("finish_reason"))})
    return buffer.result()

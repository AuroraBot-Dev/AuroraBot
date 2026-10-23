"""默认上下文装配及调用前的确定性大小限制。"""

from __future__ import annotations

import json

from aurora_agent.contracts import ContextBudgetError, ContextInput, ModelRequest
from aurora_agent.data import mutable_json
from aurora_agent.messages import ChatMessage


class DefaultContextAssembler:
    """保留完整历史，不静默裁剪任务、约束或工具结果。"""

    async def assemble(self, context: ContextInput) -> tuple[ChatMessage, ...]:
        return (ChatMessage.system(context.instructions), *context.messages)


def check_context_budget(request: ModelRequest, limit: int) -> None:
    """统计规范化消息与工具 JSON 的字符数；模型 token 预算由适配器或自定义装配器校验。"""
    data = {
        "messages": [
            {
                "role": message.role,
                "content": message.content,
                "tool_call_id": message.tool_call_id,
                "is_error": message.is_error,
                "tool_calls": [
                    {"call_id": call.call_id, "name": call.name, "arguments": mutable_json(call.arguments)}
                    for call in message.tool_calls
                ],
            }
            for message in request.messages
        ],
        "tools": [
            {"name": tool.name, "description": tool.description, "parameters": mutable_json(tool.parameters)}
            for tool in request.tools
        ],
    }
    if len(json.dumps(data, ensure_ascii=False, separators=(",", ":"))) > limit:
        raise ContextBudgetError("必要上下文超过字符预算")

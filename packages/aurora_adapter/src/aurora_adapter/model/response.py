"""SDK 无关的响应收集与数值校验；结果可直接保存到 ctx。"""

import math
from collections.abc import AsyncIterator
from copy import deepcopy

from .contract import ChatChunk, ChatResponse, FinishReason, ModelProtocolError, ReasoningBlock, ToolCall


class ResponseBuffer:
    """收集一次流的当前结果；不保存片段历史，可供调用组件持续写入同一 ctx 位置。"""

    def __init__(self) -> None:
        self.text = ""
        self.reasoning_content = ""
        self.thinking_blocks: list[ReasoningBlock] = []
        self.tool_calls: list[ToolCall] = []
        self.finish_reason: FinishReason | None = None

    def append(self, chunk: ChatChunk) -> None:
        if self.finish_reason is not None:
            raise ModelProtocolError("结束片段之后不得再输出内容")
        if chunk["type"] == "text":
            self.text += chunk["text"]
        elif chunk["type"] == "reasoning":
            self.reasoning_content += chunk["text"]
        elif chunk["type"] == "thinking_block":
            self.thinking_blocks.append(deepcopy(chunk["block"]))
        elif chunk["type"] == "tool_call":
            call = chunk["tool_call"]
            if any(previous["id"] == call["id"] for previous in self.tool_calls):
                raise ModelProtocolError(f"工具调用 ID 重复：{call['id']}")
            self.tool_calls.append(deepcopy(call))
        else:
            self.finish_reason = chunk["reason"]

    def result(self) -> ChatResponse:
        if self.finish_reason is None:
            raise ModelProtocolError("响应流缺少结束片段")
        if self.finish_reason == "tool_calls" and not self.tool_calls:
            raise ModelProtocolError("工具调用结束必须提供完整工具请求")
        result: ChatResponse = {
            "text": self.text,
            "tool_calls": deepcopy(self.tool_calls),
            "finish_reason": self.finish_reason,
        }
        if self.reasoning_content:
            result["reasoning_content"] = self.reasoning_content
        if self.thinking_blocks:
            result["thinking_blocks"] = deepcopy(self.thinking_blocks)
        return result


async def collect_response(chunks: AsyncIterator[ChatChunk]) -> ChatResponse:
    """在响应流的上下文内收集完整结果；资源关闭仍由外层 async with 负责。"""
    buffer = ResponseBuffer()
    async for chunk in chunks:
        buffer.append(chunk)
    return buffer.result()


def normalize_vectors(value: object, count: int) -> list[list[float]]:
    """校验批次数、维数及数值，并归一化为用于余弦检索的单位向量。"""
    if not isinstance(value, list) or len(value) != count:
        raise ModelProtocolError("向量响应数量与输入不一致")
    result = []
    dimension = None
    for vector in value:
        if not isinstance(vector, list) or not vector or (dimension is not None and len(vector) != dimension):
            raise ModelProtocolError("向量必须非空且维数一致")
        if any(type(v) not in (int, float) or not math.isfinite(v) for v in vector):
            raise ModelProtocolError("向量包含无效数值")
        norm = math.hypot(*vector)
        if not norm or not math.isfinite(norm):
            raise ModelProtocolError("向量范数必须有限且大于零")
        dimension = len(vector)
        result.append([v / norm for v in vector])
    return result

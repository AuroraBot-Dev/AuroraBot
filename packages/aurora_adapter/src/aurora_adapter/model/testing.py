"""离线开发用的确定性假模型；脚本决定响应，公开计数便于验证资源收尾。"""

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from copy import deepcopy
from dataclasses import dataclass

from .content import require_capabilities
from .contract import (
    ChatCapabilities,
    ChatChunk,
    ChatRequest,
    ChatResponse,
    FinishReason,
    ModelError,
    ReasoningBlock,
    ToolCall,
)
from .response import collect_response


@dataclass(frozen=True)
class FakeReply:
    """先输出文本，再输出完整工具请求和终止；error 表示文本输出后的失败。"""

    texts: tuple[str, ...] = ()
    tool_calls: tuple[ToolCall, ...] = ()
    finish_reason: FinishReason | None = None
    error: ModelError | None = None
    reasoning: tuple[str, ...] = ()
    thinking_blocks: tuple[ReasoningBlock, ...] = ()


class FakeModel:
    """每次调用通过 respond 生成响应；delay 用于演示增量及取消，不访问网络。

    requests 仅供测试检查输入，不属于 ctx 数据或正式模型客户端的必备接口。
    """

    def __init__(
        self,
        respond: Callable[[ChatRequest], FakeReply],
        *,
        capabilities: ChatCapabilities | None = None,
        delay: float = 0,
    ) -> None:
        self.respond = respond
        self.capabilities = capabilities or ChatCapabilities(streaming=True, tool_calls=True)
        self.delay = delay
        self.requests: list[ChatRequest] = []
        self.active_streams = 0
        self.closed = False

    async def _chunks(self, request: ChatRequest) -> AsyncIterator[ChatChunk]:
        reply = self.respond(request)
        for text in reply.reasoning:
            await asyncio.sleep(self.delay)
            yield {"type": "reasoning", "text": text}
        for block in reply.thinking_blocks:
            yield {"type": "thinking_block", "block": deepcopy(block)}
        for text in reply.texts:
            await asyncio.sleep(self.delay)
            yield {"type": "text", "text": text}
        if reply.error is not None:
            raise reply.error
        for call in reply.tool_calls:
            await asyncio.sleep(self.delay)
            yield {"type": "tool_call", "tool_call": deepcopy(call)}
        await asyncio.sleep(self.delay)
        yield {"type": "finish", "reason": reply.finish_reason or ("tool_calls" if reply.tool_calls else "stop")}

    @asynccontextmanager
    async def _open(self, request: ChatRequest, *, streaming: bool) -> AsyncIterator[AsyncIterator[ChatChunk]]:
        if self.closed:
            raise ModelError("模型客户端已关闭")
        require_capabilities(self, request, streaming=streaming)
        self.requests.append(deepcopy(request))
        self.active_streams += 1
        chunks = self._chunks(deepcopy(request))
        try:
            yield chunks
        finally:
            await chunks.aclose()
            self.active_streams -= 1

    def stream(self, request: ChatRequest) -> AbstractAsyncContextManager[AsyncIterator[ChatChunk]]:
        return self._open(request, streaming=True)

    async def complete(self, request: ChatRequest) -> ChatResponse:
        async with self._open(request, streaming=False) as chunks:
            return await collect_response(chunks)

    async def aclose(self) -> None:
        if self.active_streams:
            raise ModelError("关闭客户端前必须结束在途响应流")
        self.closed = True

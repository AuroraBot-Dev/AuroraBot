"""从 ctx 读取模型请求，在同一输出位置更新文本及调用状态。"""

import asyncio
from typing import Literal, NotRequired, TypedDict, cast
from uuid import uuid4

from aurora_adapter.model import (
    ChatClient,
    ChatRequest,
    FinishReason,
    ReasoningBlock,
    ResponseBuffer,
    ToolCall,
    require_capabilities,
)
from aurora_adapter.model.usage import usage_scope
from aurora_control import ExecutionPlug, ExecutionRequest, StateBinding, component_entries
from aurora_core.ctx import Context
from aurora_core.discovery import Plugin
from aurora_core.ids import Id


class ModelCallState(TypedDict):
    """单次模型调用的当前输出；取消或失败保留已经收到的内容。"""

    status: Literal["running", "completed", "cancelled", "failed"]
    execution_id: str
    text: str
    reasoning_content: NotRequired[str]
    thinking_blocks: NotRequired[list[ReasoningBlock]]
    tool_calls: list[ToolCall]
    finish_reason: FinishReason | None
    error: NotRequired[str]


class ModelCall:
    """可连接到控制组件的模型调用实例；服务对象由装配持有，调用不关闭客户端。

    request_state 保存 ChatRequest 普通数据，output_state 保存 ModelCallState。
    同一输出地址的调用应由装配串行化；不同 run_id 使用不同地址，客户端并发能力另行约定。
    completed 表示推理请求正常结束，业务是否完成仍须结合 finish_reason 判断。
    """

    definition_id = Id("org.aurora.agent:handlers/model_call")

    def __init__(
        self,
        ctx: Context,
        client: ChatClient,
        *,
        instance_id: str | None = None,
        request_state: StateBinding,
        output_state: StateBinding,
        streaming: bool = True,
    ) -> None:
        self.instance_id = uuid4().hex if instance_id is None else instance_id
        if not isinstance(self.instance_id, str) or not self.instance_id:
            raise ValueError("组件实例标识必须为非空字符串")
        self.ctx = ctx
        self.client = client
        self.request_state = request_state
        self.output_state = output_state
        self.streaming = streaming

    @property
    def plug(self) -> ExecutionPlug:
        return ExecutionPlug(
            self.definition_id,
            self.execute,
            {"input": self.request_state, "output": self.output_state},
            instance_id=self.instance_id,
        )

    async def execute(self, execution: ExecutionRequest) -> None:
        buffer = ResponseBuffer()

        def write(
            status: Literal["running", "completed", "cancelled", "failed"], error: Exception | None = None
        ) -> None:
            state: ModelCallState = {
                "status": status,
                "execution_id": execution.execution_id,
                "text": buffer.text,
                "tool_calls": buffer.tool_calls,
                "finish_reason": buffer.finish_reason,
            }
            if error is not None:
                state["error"] = type(error).__name__
            if buffer.reasoning_content:
                state["reasoning_content"] = buffer.reasoning_content
            if buffer.thinking_blocks:
                state["thinking_blocks"] = buffer.thinking_blocks
            self.output_state.set(self.ctx, execution, state)

        write("running")
        with usage_scope("inference", run_id=execution.run_id, execution_id=execution.execution_id):
            try:
                value = self.request_state.get(self.ctx, execution)
                if not isinstance(value, dict):
                    raise TypeError("模型输入必须为 ChatRequest 字典")
                # 地址的具体结构由装配或 StateKey 校验器约定，不建立全局 schema 匹配系统。
                request = cast(ChatRequest, value)
                require_capabilities(self.client, request, streaming=self.streaming)
                if self.streaming:
                    async with self.client.stream(request) as chunks:
                        async for chunk in chunks:
                            buffer.append(chunk)
                            write("running")
                        buffer.result()
                else:
                    response = await self.client.complete(request)
                    buffer.text = response["text"]
                    buffer.reasoning_content = response.get("reasoning_content", "")
                    buffer.thinking_blocks = response.get("thinking_blocks", [])
                    buffer.tool_calls = response["tool_calls"]
                    buffer.finish_reason = response["finish_reason"]
                    buffer.result()
            except asyncio.CancelledError:
                write("cancelled")
                raise
            except Exception as error:
                write("failed", error)
                raise
            else:
                write("completed")


def plugin() -> Plugin:
    """声明模型调用组件及执行入口；客户端与实例由装配创建。"""
    return Plugin(
        "aurora_agent.model",
        component_entries(ModelCall.definition_id, ModelCall, ModelCall.execute, provider="aurora_agent"),
    )

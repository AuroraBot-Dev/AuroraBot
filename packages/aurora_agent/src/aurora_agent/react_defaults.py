"""默认 ReAct 阶段：准备上下文、解释模型决定和回填工具观察。"""

import logging
from typing import NotRequired, TypedDict, cast

from aurora_control import ExecutionPlug, ExecutionRequest
from aurora_core import plug
from aurora_core.components import ComponentFactory, InstanceExport
from aurora_core.ctx import Context
from aurora_core.discovery import Plugin
from aurora_core.json_data import encode_json
from aurora_model import ChatRequest, Message, ModelProtocolError
from aurora_model.content import validate_content
from aurora_model.usage import usage_scope
from aurora_tools.contract import ToolBatchState, ToolCall
from aurora_tools.execution import ToolExecutor, failure, read_request

from .compaction import CompactionState, validate_compaction
from .input_budget import ModelInputBudgetExceeded, read_exchange_ends
from .model import ModelCallState
from .plugins.defaults._meta import (
    BUILD_PROMPT,
    BUILD_PROMPT_EXECUTE,
    CONFIGURE,
    INTERPRET_RESPONSE,
    INTERPRET_RESPONSE_EXECUTE,
    RECORD_OBSERVATION,
    RECORD_OBSERVATION_EXECUTE,
    defaults_plugin,
)
from .react import Guidance, ReActAgent

logger = logging.getLogger(__name__)


class PendingTurn(TypedDict):
    """已产生工具请求但尚未形成完整观察的模型轮次。"""

    run_id: str
    turn_id: str
    message: Message


class ReActContext(TypedDict):
    """上下文及引导消费位置整项写入，避免重复接纳和孤立的工具消息。

    exchange_ends 保存正常 stop 时的历史消息数，包括静默结束，不进入模型请求。
    宿主裁剪消息时须同步平移并过滤结束位置；旧快照可缺少此字段。
    """

    messages: list[Message]
    guidance_sequence: int
    pending: PendingTurn | None
    exchange_ends: NotRequired[list[int]]
    compaction: NotRequired[CompactionState]


class ReActDefaults:
    """默认阶段通过明确状态地址交换数据，接线由宿主装配提供。

    context_state 是实例级 ReActContext，prepare 原子保存消息与已接纳的引导位置。
    字符串与 kind=model_input 的结构化引导作为 user 内容，其他 JSON 编码为环境输入。
    模型文本保留在上下文中，不自动发布为用户消息；无工具请求即允许结束。
    工具请求与全部结果一起回填，普通工具失败仍作为 tool 消息进入下一次推理。
    context_view 在每次 prepare 同步生成临时 user 观察，置于历史之前，不写入 context。

    后续激活遇到 pending 时保留可获得的工具结果，将其余标记 interrupted，
    不自动重跑动作、不假定中断的动作没有副作用。恢复所需的工具输出由装配保留，
    context、inbox 与工具记录的裁剪同样由装配负责。本组件不关闭共享模型客户端。
    """

    def __init__(self, ctx: Context, *, instance_id: str, states, system_prompt: str = "") -> None:
        self.ctx, self.instance_id, self.states = ctx, instance_id, states
        self.context_state = states["context"]
        self.system_prompt = system_prompt
        self.agent: ReActAgent
        self.tools: ToolExecutor
        self.context_view = None
        self.input_budget = None
        self.compactor = None
        self.tool_observation = None

    def bind(self, *, agent, tools, context_view=None, input_budget=None, compactor=None, tool_observation=None):
        self.agent, self.tools = agent, tools
        self.context_view, self.input_budget = context_view, input_budget
        self.compactor, self.tool_observation = compactor, tool_observation

    @plug(CONFIGURE)
    def configure(self):
        if "config" in self.states:
            self.system_prompt = self.states["config"].get(self.ctx, ExecutionRequest("config"))["system_prompt"]

    def execution_plugs(self):
        return {
            identity: ExecutionPlug(definition, method, self.states, instance_id=self.instance_id, port_id=identity)
            for definition, identity, method in (
                (BUILD_PROMPT, BUILD_PROMPT_EXECUTE, self.build_prompt),
                (INTERPRET_RESPONSE, INTERPRET_RESPONSE_EXECUTE, self.interpret_response),
                (RECORD_OBSERVATION, RECORD_OBSERVATION_EXECUTE, self.record_observation),
            )
        }

    def _context(self, request: ExecutionRequest) -> ReActContext:
        try:
            value = self.context_state.get(self.ctx, request)
        except KeyError:
            return {"messages": [], "guidance_sequence": 0, "pending": None, "exchange_ends": []}
        if (
            not isinstance(value, dict)
            or not isinstance(value.get("messages"), list)
            or type(value.get("guidance_sequence")) is not int
            or value["guidance_sequence"] < 0
            or "pending" not in value
        ):
            raise ValueError("ReAct 上下文格式无效")
        context = cast(ReActContext, value)
        if "exchange_ends" not in context:
            context["exchange_ends"] = [
                index + 1
                for index, message in enumerate(context["messages"])
                if message["role"] == "assistant" and not message.get("tool_calls")
            ]
        read_exchange_ends(context["messages"], context["exchange_ends"])
        if "compaction" in context:
            validate_compaction(context["messages"], context["compaction"])
        return context

    def _settle(self, context: ReActContext, *, recovering: bool) -> None:
        pending = context["pending"]
        if pending is None:
            if not recovering:
                raise ValueError("没有待接纳的工具轮次")
            return
        calls = pending["message"].get("tool_calls", [])
        try:
            value = self.states["tool_output"].get(self.ctx, ExecutionRequest(pending["run_id"]))
        except KeyError:
            value = None
        matching = isinstance(value, dict) and value.get("turn_id") == pending["turn_id"]
        if not recovering and (not matching or cast(dict, value).get("status") != "completed"):
            raise ValueError("工具批次尚未完成或与待接纳轮次不符")
        results = cast(ToolBatchState, value)["results"] if matching else []
        by_id = {result["call_id"]: result for result in results}
        if len(by_id) != len(results):
            raise ValueError("工具结果的调用身份重复")
        observations: list[Message] = []
        for call in calls:
            result = by_id.get(call["id"])
            if result is None:
                if not recovering:
                    raise ValueError("工具批次缺少调用结果")
                result = failure(call, "interrupted", "没有完整工具结果，动作是否完成需核实；未自动重试")
            if result["name"] != call["name"] or result["status"] not in ("completed", "failed", "cancelled"):
                raise ValueError("工具结果与原始请求不符")
            content = self.tool_observation(pending["run_id"], result) if self.tool_observation else encode_json(result)
            observations.append({"role": "tool", "tool_call_id": call["id"], "content": content})
        context["messages"].extend([pending["message"], *observations])
        context["pending"] = None

    @plug(BUILD_PROMPT_EXECUTE)
    async def build_prompt(self, request: ExecutionRequest) -> None:
        context = self._context(request)
        self._settle(context, recovering=True)
        batch = self.states["batch"].get(self.ctx, request)
        if not isinstance(batch, list):
            raise TypeError("prepare 需要引导 batch 列表")
        for item in cast(list[Guidance], batch):
            if item["sequence"] > context["guidance_sequence"]:
                payload = item["payload"]
                content = payload if isinstance(payload, str) else encode_json(payload)
                if isinstance(payload, dict) and payload.get("kind") == "model_input":
                    if set(payload) != {"kind", "content"}:
                        raise ValueError("模型输入引导字段无效")
                    content = validate_content(payload["content"])
                context["messages"].append({"role": "user", "content": content})
                context["guidance_sequence"] = item["sequence"]
        self.context_state.set(self.ctx, request, context)
        messages = list(context["messages"])
        if self.context_view is not None:
            view = self.context_view(request)
            if not isinstance(view, str):
                raise TypeError("上下文视图必须返回文本")
            if view:
                messages.insert(0, {"role": "user", "content": view})
        if self.system_prompt:
            messages.insert(0, {"role": "system", "content": self.system_prompt})
        model_request: ChatRequest = {"messages": messages}
        definitions = self.tools.definitions()
        if definitions:
            model_request["tools"] = definitions
        if self.input_budget is not None:
            try:
                history_start = len(messages) - len(context["messages"])
                if self.compactor is not None:
                    with usage_scope("summary", run_id=request.run_id, execution_id=request.execution_id):
                        model_request, compacted = await self.compactor.apply(
                            model_request,
                            history_start=history_start,
                            exchange_ends=context["exchange_ends"],
                            state=context.get("compaction"),
                            run_id=request.run_id,
                        )
                    if compacted is not None:
                        context["compaction"] = compacted
                        self.context_state.set(self.ctx, request, context)
                else:
                    model_request = self.input_budget.apply(
                        model_request,
                        history_start=history_start,
                        exchange_ends=context["exchange_ends"],
                    )
            except ModelInputBudgetExceeded as error:
                logger.error("模型输入超限：%s", error)
                address = self.states["model_input"].address(request)
                self.ctx.delete(address.key, location=dict(address.location))
                raise
        self.states["model_input"].set(self.ctx, request, model_request)

    @plug(INTERPRET_RESPONSE_EXECUTE)
    async def interpret_response(self, request: ExecutionRequest) -> None:
        value = self.states["model_output"].get(self.ctx, request)
        if not isinstance(value, dict) or value.get("status") != "completed":
            raise ModelProtocolError("模型尚未完成")
        response = cast(ModelCallState, value)
        calls: list[ToolCall] = response["tool_calls"]
        expected = "tool_calls" if calls else "stop"
        if response["finish_reason"] != expected:
            raise ModelProtocolError("模型没有形成完整且一致的行动决定")
        batch = read_request({"turn_id": response["execution_id"], "calls": calls})
        context = self._context(request)
        if context["pending"] is not None:
            raise ValueError("上一工具轮次尚未接纳")
        message: Message = {"role": "assistant", "content": response["text"]}
        if "reasoning_content" in response:
            message["reasoning_content"] = response["reasoning_content"]
        if "thinking_blocks" in response:
            message["thinking_blocks"] = response["thinking_blocks"]
        if calls:
            message["tool_calls"] = calls
            context["pending"] = {"run_id": request.run_id, "turn_id": batch["turn_id"], "message": message}
        else:
            if response["text"] or response.get("reasoning_content") or response.get("thinking_blocks"):
                context["messages"].append(message)
            end = len(context["messages"])
            ends = context["exchange_ends"]
            if end and (not ends or ends[-1] != end):
                ends.append(end)
        self.context_state.set(self.ctx, request, context)
        self.states["tool_input"].set(self.ctx, request, batch)
        self.states["decision"].set(self.ctx, request, "act" if calls else "finish")

    @plug(RECORD_OBSERVATION_EXECUTE)
    async def record_observation(self, request: ExecutionRequest) -> None:
        context = self._context(request)
        self._settle(context, recovering=False)
        if self.agent.finish_requested:
            context["exchange_ends"].append(len(context["messages"]))
        self.context_state.set(self.ctx, request, context)


def _create(*, ctx, instance_id, states, options):
    if "config" in states and options:
        raise ValueError("默认阶段参数须选择配置状态或显式 options")
    return ReActDefaults(ctx, instance_id=instance_id, states=states, **options)


def plugin() -> Plugin:
    from .context_resources import factories

    return defaults_plugin(
        targets={BUILD_PROMPT: ReActDefaults, INTERPRET_RESPONSE: ReActDefaults, RECORD_OBSERVATION: ReActDefaults},
        components={
            **factories(),
            "defaults": ComponentFactory(
                _create,
                lambda instance: InstanceExport(
                    plugs={**instance.execution_plugs(), CONFIGURE: instance.configure},
                    resources={"defaults": instance},
                ),
                plugs=(
                    ReActDefaults.build_prompt,
                    ReActDefaults.interpret_response,
                    ReActDefaults.record_observation,
                    ReActDefaults.configure,
                ),
                bind=lambda instance, resources: instance.bind(**resources),
            ),
        },
    )

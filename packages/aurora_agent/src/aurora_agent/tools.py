"""显式登记与连接工具，通过 ctx 执行请求并保留结构化观察。"""

import asyncio
import logging
import math
from collections.abc import Awaitable, Callable
from copy import deepcopy
from dataclasses import dataclass
from typing import Literal, NotRequired, Protocol, TypedDict, cast
from uuid import uuid4

from aurora_adapter.model import JsonValue, ToolCall, ToolDefinition
from aurora_control import (
    ExecutionLink,
    ExecutionPlug,
    ExecutionRequest,
    ExecutionSlot,
    StateBinding,
    component_entries,
    execution_slot_entry,
)
from aurora_core.bootstrap import REGISTRY_DIRECTORY
from aurora_core.ctx import Context
from aurora_core.discovery import Plugin
from aurora_core.hooks import HookConnections
from aurora_core.ids import Id
from aurora_core.json_data import encode_json
from aurora_core.registry import DefinitionRegistry, RegistryEntry
from aurora_core.storage import StorageService
from jsonschema import Draft202012Validator, ValidationError
from referencing import Registry

TOOLS = Id("org.aurora.agent:registries/tools")
BEFORE_CALL = Id("org.aurora.agent:tools/before_call")
AFTER_CALL = Id("org.aurora.agent:tools/after_call")
_logger = logging.getLogger(__name__)


class ToolBatchRequest(TypedDict):
    """一次推理产生的工具批次，turn_id 用于排除其他推理留下的结果。"""

    turn_id: str
    calls: list[ToolCall]


class ToolResult(TypedDict):
    """可进入模型观察的单次结果；取消及未执行也有明确状态。"""

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


class ToolRecorder(Protocol):
    """同步记录执行边界；失败阻止继续调用，持久化与查询策略由宿主负责。

    begin 原子接纳整个批次；start 在调用前执行，finish 在结果接纳前执行。
    记录器不得修改传入的请求或结果，不得将记录失败解释为可重试动作。
    """

    def begin(self, request: ExecutionRequest, batch: ToolBatchRequest) -> None: ...

    def start(self, request: ExecutionRequest, call: ToolCall) -> None: ...

    def finish(self, request: ExecutionRequest, result: ToolResult) -> None: ...


class ToolExecutionError(Exception):
    """工具主动提供的安全失败观察；value 可保留业务错误的 JSON 内容。

    code、message 和 value 会进入模型观察及业务状态，不应包含凭证或原始传输异常。
    """

    def __init__(self, code: str, message: str, *, value: JsonValue = None) -> None:
        if not code or not message:
            raise ValueError("工具失败须提供错误码和消息")
        encode_json(value)
        super().__init__(message)
        self.code, self.message, self.value = code, message, deepcopy(value)


def failure(call: ToolCall, code: str, message: str, *, cancelled: bool = False) -> ToolResult:
    """将可观察失败关联到原始工具调用。"""
    return {
        "call_id": call["id"],
        "name": call["name"],
        "status": "cancelled" if cancelled else "failed",
        "error": {"code": code, "message": message},
    }


def read_request(value: object) -> ToolBatchRequest:
    """执行前完整校验批次信封；格式错误不执行其中任何工具。"""
    encode_json(value)
    if not isinstance(value, dict) or not isinstance(value.get("turn_id"), str) or not value["turn_id"]:
        raise ValueError("工具批次必须提供非空 turn_id")
    if not isinstance(value.get("calls"), list):
        raise TypeError("工具批次必须提供 calls 列表")
    identities: set[str] = set()
    for call in value["calls"]:
        if (
            not isinstance(call, dict)
            or not isinstance(call.get("id"), str)
            or not call["id"]
            or call["id"] in identities
            or not isinstance(call.get("name"), str)
            or not call["name"]
            or not isinstance(call.get("arguments"), dict)
        ):
            raise ValueError("工具请求需要唯一 id、非空 name 和完整 arguments 对象")
        identities.add(call["id"])
    return cast(ToolBatchRequest, value)


@dataclass(frozen=True)
class ToolInstance:
    """工厂创建的工具及其资源关闭入口；关闭失败时宿主保留实例供重试。"""

    plug: ExecutionPlug
    aclose: Callable[[], Awaitable[None]] | None = None


class ToolFactory(Protocol):
    """异步创建显式工具实例；返回前失败或取消时，工厂负责释放自身部分资源。

    插头须沿用装配分配的 instance_id 与 input/output 地址，config 为该工具的 JSON 配置。
    与模型一样，共享 storage 由宿主关闭，不由工具工厂关闭。
    """

    async def __call__(
        self,
        *,
        ctx: Context,
        storage: StorageService,
        instance_id: str,
        input_state: StateBinding,
        output_state: StateBinding,
        config: dict[str, JsonValue],
    ) -> ToolInstance: ...


class ToolSpec:
    """工具定义引用组件身份；运行时实例在 ToolExecutor 中显式连接。

    参数按 JSON Schema Draft 2020-12 校验；format 为注释，不获取外部 schema。
    工具通过 input 地址读取完整 ToolCall，通过 output 写入 JSON 结果。
    """

    def __init__(self, component: Id, definition: ToolDefinition, *, factory: ToolFactory | None = None) -> None:
        encode_json(definition)
        if not isinstance(component, Id):
            raise TypeError("工具组件身份必须为 Id")
        if not isinstance(definition.get("name"), str) or not definition["name"]:
            raise ValueError("工具名称必须为非空字符串")
        if not isinstance(definition.get("description"), str):
            raise TypeError("工具描述必须为字符串")
        schema = definition.get("parameters")
        if not isinstance(schema, dict) or schema.get("type") != "object":
            raise ValueError("工具参数 schema 必须声明 object 类型")
        if (
            schema.get("$schema", "https://json-schema.org/draft/2020-12/schema")
            != "https://json-schema.org/draft/2020-12/schema"
        ):
            raise ValueError("工具参数使用 JSON Schema Draft 2020-12")
        Draft202012Validator.check_schema(schema)
        self.component = component
        if factory is not None and not callable(factory):
            raise TypeError("工具工厂必须可调用")
        self.factory = factory
        self._definition = deepcopy(definition)
        self._validator = Draft202012Validator(self._definition["parameters"], registry=Registry())

    @property
    def definition(self) -> ToolDefinition:
        return deepcopy(self._definition)

    def validate(self, arguments: dict[str, JsonValue]) -> None:
        self._validator.validate(arguments)


class ToolReceiver:
    def rejection_reason(self, entry: RegistryEntry) -> str | None:
        return None if entry.kind == "tool" and isinstance(entry.target, ToolSpec) else "工具登记需要 ToolSpec"


class ToolRejected(ValueError):
    """before_call 显式拒绝工具，原因作为观察交回 bot。"""


class ToolExecutor:
    """按请求顺序执行已连接工具；普通失败和超时产生观察，取消传播并等待清理。

    before_call 可抛 ToolRejected 拒绝动作；after_call 观察已经保存的结果。
    两者通过 current 地址读取 call/result，不隐式修改实际参数或结果。
    扩展处理器故障、不可用 schema 等装配错误传播，不伪装成工具业务失败。
    timeout 限制一次 before_call 和工具执行，以及一次 after_call；同步阻塞无法被抢占。
    工具 input/output 为本次调用的临时工作地址，结果复制到批次后清理；持久业务数据另存。
    工具不得留下未托管的后台任务；本组件不做自动重试或动作去重。
    """

    definition_id = Id("org.aurora.agent:handlers/react/execute_tools")

    def __init__(
        self,
        ctx: Context,
        registry: DefinitionRegistry,
        hooks: HookConnections,
        *,
        request_state: StateBinding,
        output_state: StateBinding,
        current_state: StateBinding,
        timeout: float,
        instance_id: str | None = None,
        recorder: ToolRecorder | None = None,
    ) -> None:
        if isinstance(timeout, bool) or not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("工具超时必须为正有限数")
        self.ctx, self.registry = ctx, registry
        self.instance_id = uuid4().hex if instance_id is None else instance_id
        self.request_state, self.output_state, self.current_state = request_state, output_state, current_state
        self.timeout = timeout
        self.recorder = recorder
        self.states = {"input": request_state, "output": output_state, "current": current_state}
        probe = ExecutionRequest("binding-check")
        if len({binding.address(probe) for binding in self.states.values()}) != 3:
            raise ValueError("工具批次输入、结果和当前调用地址不得重叠")
        self.slot = ExecutionSlot(self.definition_id, hooks, instance_id=self.instance_id, states=self.states)
        self.before = ExecutionSlot(
            self.definition_id, hooks, instance_id=self.instance_id, slot_id=BEFORE_CALL, states=self.states
        )
        self.after = ExecutionSlot(
            self.definition_id, hooks, instance_id=self.instance_id, slot_id=AFTER_CALL, states=self.states
        )
        self._tools: dict[str, tuple[ToolSpec, ExecutionLink]] = {}
        self._active = False

    @property
    def plug(self) -> ExecutionPlug:
        return ExecutionPlug(self.definition_id, self.execute, self.states, instance_id=self.instance_id)

    def connect(self, identity: Id, plug: ExecutionPlug) -> ExecutionLink:
        """选择登记工具并绑定实例；模型名称在同一执行器内唯一。"""
        entry = self.registry.get(identity)
        if entry.kind != "tool" or entry.register_to != TOOLS or not isinstance(entry.target, ToolSpec):
            raise ValueError("目标不是已登记工具")
        spec = entry.target
        if plug.definition_id != spec.component or not {"input", "output"} <= plug.states.keys():
            raise ValueError("工具插头须匹配组件并提供 input/output 地址")
        probe = ExecutionRequest("binding-check")
        working = {plug.states[name].address(probe) for name in ("input", "output")}
        if len(working) != 2 or working.intersection(binding.address(probe) for binding in self.states.values()):
            raise ValueError("工具工作地址不得互相重叠或覆盖批次状态")
        name = spec.definition["name"]
        if name in self._tools:
            raise ValueError(f"工具名称重复：{name}")
        link = self.slot.connect(plug)
        self._tools[name] = spec, link
        return link

    def definitions(self) -> list[ToolDefinition]:
        """只向模型公布实际已连接的工具，定义数据返回独立副本。"""
        active = self.slot.links()
        return [spec.definition for spec, link in self._tools.values() if link in active]

    async def _hooks(self, slot: ExecutionSlot, request: ExecutionRequest) -> None:
        for link in slot.links():
            await slot.invoke(link, request.child())

    async def _call(self, call: ToolCall, request: ExecutionRequest) -> ToolResult:
        selected = self._tools.get(call["name"])
        if selected is None or selected[1] not in self.slot.links():
            return failure(call, "unknown_tool", "工具未连接")
        spec, link = selected
        try:
            spec.validate(call["arguments"])
        except ValidationError:
            return failure(call, "invalid_arguments", "参数不符合工具 schema")
        try:
            async with asyncio.timeout(self.timeout):
                await self._hooks(self.before, request)
                output = link.plug.states["output"].address(request)
                self.ctx.delete(output.key, location=dict(output.location))
                link.plug.states["input"].set(self.ctx, request, call)
                if self.recorder is not None:
                    try:
                        self.recorder.start(request, deepcopy(call))
                    except Exception as error:
                        raise RuntimeError("工具执行记录失败，未调用工具") from error
                try:
                    await self.slot.invoke(link, request.child())
                except ToolExecutionError as error:
                    result = failure(call, error.code, error.message)
                    if error.value is not None:
                        result["value"] = error.value
                    return result
                except TimeoutError:
                    raise
                except Exception as error:
                    _logger.exception("工具 %s 执行失败", call["name"])
                    return failure(call, "tool_failed", type(error).__name__)
                try:
                    value = link.plug.states["output"].get(self.ctx, request)
                    encode_json(value)
                except (KeyError, TypeError, ValueError):
                    return failure(call, "invalid_result", "工具未提供有效 JSON 结果")
                return {
                    "call_id": call["id"],
                    "name": call["name"],
                    "status": "completed",
                    "value": cast(JsonValue, value),
                }
        except TimeoutError:
            return failure(call, "timeout", "工具执行超时，动作结果需核实")
        except ToolRejected as error:
            return failure(call, "rejected", str(error))
        finally:
            for name in ("input", "output"):
                address = link.plug.states[name].address(request)
                self.ctx.delete(address.key, location=dict(address.location))

    async def execute(self, request: ExecutionRequest) -> None:
        if self._active:
            raise RuntimeError("工具执行器正在运行")
        batch = read_request(self.request_state.get(self.ctx, request))
        self._active = True
        results: list[ToolResult] = []

        def write(status: Literal["running", "completed", "failed", "cancelled"]) -> None:
            state: ToolBatchState = {
                "turn_id": batch["turn_id"],
                "execution_id": request.execution_id,
                "status": status,
                "results": results,
            }
            self.output_state.set(self.ctx, request, state)

        try:
            if self.recorder is not None:
                self.recorder.begin(request, deepcopy(batch))
            write("running")
            for call in batch["calls"]:
                self.current_state.set(self.ctx, request, {"call": call, "result": None})
                try:
                    result = await self._call(call, request)
                except asyncio.CancelledError:
                    result = failure(call, "cancelled", "工具调用已取消，动作结果需核实", cancelled=True)
                    if self.recorder is not None:
                        self.recorder.finish(request, deepcopy(result))
                    results.append(result)
                    raise
                if self.recorder is not None:
                    self.recorder.finish(request, deepcopy(result))
                results.append(result)
                write("running")
                self.current_state.set(self.ctx, request, {"call": call, "result": result})
                async with asyncio.timeout(self.timeout):
                    await self._hooks(self.after, request)
            write("completed")
        except asyncio.CancelledError:
            for call in batch["calls"][len(results) :]:
                results.append(failure(call, "not_executed", "本次取消前尚未执行"))
            write("cancelled")
            raise
        except Exception:
            write("failed")
            raise
        finally:
            self._active = False
            address = self.current_state.address(request)
            self.ctx.delete(address.key, location=dict(address.location))


def plugin() -> Plugin:
    return Plugin(
        "aurora_agent.tools",
        (
            RegistryEntry(TOOLS, "registry", ToolReceiver(), "aurora_agent", register_to=REGISTRY_DIRECTORY),
            *component_entries(
                ToolExecutor.definition_id, ToolExecutor, ToolExecutor.execute, provider="aurora_agent", children=True
            ),
            execution_slot_entry(BEFORE_CALL, provider="aurora_agent"),
            execution_slot_entry(AFTER_CALL, provider="aurora_agent"),
        ),
    )

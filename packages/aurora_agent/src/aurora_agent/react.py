"""可重复激活的 ReAct 组件；在推理边界接纳引导，阶段行为由显式连接提供。"""

import asyncio
from itertools import count
from typing import Literal, TypedDict, cast
from uuid import uuid4

from aurora_adapter.model import JsonValue
from aurora_control import (
    ExecutionPlug,
    ExecutionRequest,
    ExecutionSlot,
    InstanceStateBinding,
    LoopLimitExceeded,
    StateBinding,
    component_entries,
    execution_slot_entry,
)
from aurora_core.ctx import Context
from aurora_core.discovery import Plugin
from aurora_core.hooks import HookConnections
from aurora_core.ids import Id

type Phase = Literal["prepare", "infer", "act", "observe", "finish", "error"]
type Decision = Literal["act", "continue", "finish"]

PHASE_IDS: dict[Phase, Id] = {
    name: Id(f"org.aurora.agent:react/{name}") for name in ("prepare", "infer", "act", "observe", "finish", "error")
}


class Guidance(TypedDict):
    """cadence 写入的持续输入；sequence 跨激活严格递增，id 唯一。

    裁剪已消费记录时仍须保留序号的单调性，不复用 progress 及其之前的序号。
    """

    sequence: int
    id: str
    payload: JsonValue


class AgentBusyError(RuntimeError):
    """同一实例正在执行；新引导应进入 inbox，由当前激活接纳。"""


class ReActAgent:
    """一次 execute 等待一次激活收束，不创建后台任务或自动订阅 world。

    inbox 为 Guidance 列表，progress 为已接纳的 sequence，缺失分别视为空列表和 0。
    runtime 保留实例最近一次激活的状态。三者使用不同的实例级地址，由装配隔离实例。
    batch 保存本次 prepare 的输入快照，decision 由 infer 写入 act/continue/finish。
    prepare 须将 batch 纳入可保留的上下文；成功后才推进 progress，表示已接纳而非已完成。
    prepare 失败可能重试同一批输入，处理器须按 Guidance.id 避免重复纳入上下文。

    prepare/infer 必须连接；act 决策要求 act/observe 均已连接。每个阶段按 priority
    顺序等待处理器，各子调用具有独立 execution_id。finish/error 可无处理器。
    finish 开始后的输入留给调度所有者在 execute 返回后复查；失败和取消不自动重试。
    业务上下文和模型输出的保留由装配负责，本组件仅清理 batch/decision 临时地址。
    """

    definition_id = Id("org.aurora.agent:handlers/react_agent")

    def __init__(
        self,
        ctx: Context,
        hooks: HookConnections,
        *,
        inbox: InstanceStateBinding,
        progress: InstanceStateBinding,
        runtime: InstanceStateBinding,
        batch: StateBinding,
        decision: StateBinding,
        max_iterations: int | None = None,
        instance_id: str | None = None,
    ) -> None:
        if max_iterations is not None and (type(max_iterations) is not int or max_iterations < 1):
            raise ValueError("循环上限必须为正整数")
        self.instance_id = uuid4().hex if instance_id is None else instance_id
        self.ctx = ctx
        self.inbox = inbox
        self.progress = progress
        self.runtime = runtime
        self.batch = batch
        self.decision = decision
        self.max_iterations = max_iterations
        self._active = False
        self._finish_requested = False
        self.states = {"inbox": inbox, "progress": progress, "runtime": runtime, "batch": batch, "decision": decision}
        for binding in (inbox, progress, runtime):
            if not isinstance(binding, InstanceStateBinding):
                raise TypeError("inbox、progress 与 runtime 必须使用实例级绑定")
        sample = ExecutionRequest("binding-check")
        if len({binding.address(sample) for binding in self.states.values()}) != len(self.states):
            raise ValueError("ReAct 输入、进度、运行状态和临时地址不得重叠")
        self.slots = {
            phase: ExecutionSlot(
                self.definition_id,
                hooks,
                instance_id=self.instance_id,
                slot_id=slot_id,
                states=self.states,
            )
            for phase, slot_id in PHASE_IDS.items()
        }

    @property
    def plug(self) -> ExecutionPlug:
        return ExecutionPlug(self.definition_id, self.execute, self.states, instance_id=self.instance_id)

    @property
    def finish_requested(self) -> bool:
        """当前激活是否要求在本轮工具结果接纳后正常结束。"""
        return self._finish_requested

    def request_finish(self, run_id: str) -> bool:
        """仅结束匹配的活动运行；不取消本轮工具、不消费新输入或停止调度所有者。"""
        if not self._active:
            return False
        state = self.runtime.get(self.ctx, ExecutionRequest(run_id))
        if not isinstance(state, dict) or state.get("run_id") != run_id or state.get("phase") == "finish":
            return False
        self._finish_requested = True
        return True

    def pending(self, request: ExecutionRequest) -> list[Guidance]:
        """读取尚未接纳的输入；调度所有者可在执行前后复查，不消费或触发执行。"""
        try:
            progress = self.progress.get(self.ctx, request)
        except KeyError:
            progress = 0
        if type(progress) is not int or progress < 0:
            raise ValueError("引导消费位置必须为非负整数")
        try:
            value = self.inbox.get(self.ctx, request)
        except KeyError:
            value = []
        if not isinstance(value, list):
            raise TypeError("inbox 必须为引导列表")
        last = 0
        identities: set[str] = set()
        pending: list[Guidance] = []
        for item in value:
            if not isinstance(item, dict) or set(item) != {"sequence", "id", "payload"}:
                raise ValueError("引导必须包含 sequence、id 与 payload")
            sequence, identity = item["sequence"], item["id"]
            if type(sequence) is not int or sequence <= last:
                raise ValueError("引导 sequence 必须为严格递增的正整数")
            if not isinstance(identity, str) or not identity or identity in identities:
                raise ValueError("引导 id 必须为非空且唯一的字符串")
            last = sequence
            identities.add(identity)
            if sequence > progress:
                pending.append(cast(Guidance, item))
        return pending

    def _update(self, request: ExecutionRequest, **changes: object) -> None:
        state = self.runtime.get(self.ctx, request)
        assert isinstance(state, dict)
        self.runtime.set(self.ctx, request, {**state, **changes})

    async def _phase(self, phase: Phase, request: ExecutionRequest) -> None:
        self._update(request, phase=phase)
        slot = self.slots[phase]
        for link in slot.links():
            await slot.invoke(link, request.child())

    def _require(self, *phases: Phase) -> None:
        for phase in phases:
            if not self.slots[phase].links():
                raise ValueError(f"ReAct 阶段未连接：{phase}")

    async def _run(self, request: ExecutionRequest) -> None:
        self._require("prepare", "infer")
        for iteration in count(1):
            if self.max_iterations is not None and iteration > self.max_iterations:
                raise LoopLimitExceeded(f"ReAct 循环达到 {self.max_iterations} 次上限")
            self._update(request, iterations=iteration)
            incoming = self.pending(request)
            self.batch.set(self.ctx, request, incoming)
            self.decision.set(self.ctx, request, None)
            await self._phase("prepare", request)
            if incoming:
                self.progress.set(self.ctx, request, incoming[-1]["sequence"])
            await self._phase("infer", request)
            # 即使各处理器同步完成，也给外部输入和取消一个进入事件循环的机会。
            await asyncio.sleep(0)
            decision = self.decision.get(self.ctx, request)
            if decision == "act":
                self._require("act", "observe")
                await self._phase("act", request)
                await self._phase("observe", request)
            elif decision == "finish":
                if not self.pending(request):
                    await self._phase("finish", request)
                    return
            elif decision != "continue":
                raise ValueError("infer 必须写入 act、continue 或 finish 决策")
            if self._finish_requested:
                await self._phase("finish", request)
                return

    async def execute(self, request: ExecutionRequest) -> None:
        """串行执行一次激活；异常与取消传播，runtime 保留唯一终态及当前运行身份。"""
        if self._active:
            raise AgentBusyError(f"ReActAgent 正在运行：{self.instance_id}")
        self._active = True
        self._finish_requested = False
        try:
            self.runtime.set(
                self.ctx,
                request,
                {
                    "status": "running",
                    "run_id": request.run_id,
                    "execution_id": request.execution_id,
                    "parent_execution_id": request.parent_execution_id,
                    "phase": None,
                    "iterations": 0,
                },
            )
            try:
                await self._run(request)
            except asyncio.CancelledError:
                self._update(request, status="cancelled")
                raise
            except Exception as error:
                self._update(request, error=type(error).__name__)
                try:
                    await self._phase("error", request)
                except BaseException as cleanup_error:  # noqa: BLE001 — 同时保留执行和错误处理异常，包括取消。
                    raise BaseExceptionGroup("ReAct 执行与错误处理均失败", [error, cleanup_error]) from None
                finally:
                    self._update(request, status="failed")
                raise
            else:
                self._update(request, status="completed")
        finally:
            self._active = False
            self._finish_requested = False
            for binding in (self.batch, self.decision):
                address = binding.address(request)
                self.ctx.delete(address.key, location=dict(address.location))


def plugin() -> Plugin:
    """登记 ReActAgent 与六个执行阶段；业务状态定义和阶段处理器由装配提供。"""
    return Plugin(
        "aurora_agent.react",
        (
            *component_entries(ReActAgent.definition_id, ReActAgent, ReActAgent.execute, provider="aurora_agent"),
            *(execution_slot_entry(slot_id, provider="aurora_agent") for slot_id in PHASE_IDS.values()),
        ),
    )

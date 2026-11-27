"""实例隔离的计划唤醒与自身运行工具；所有引导仍由既有 AgentRuntime 接纳。"""

import asyncio
import json
import logging
import math
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from functools import partial
from importlib.resources import files
from time import time
from typing import cast

from aurora_agent.react import AgentBusyError, ReActAgent
from aurora_agent.runtime import AgentRuntime
from aurora_config import ConfigSchema
from aurora_control import ExecutionPlug, ExecutionRequest
from aurora_core import plug
from aurora_core.components import ComponentFactory, InstanceExport
from aurora_core.ctx import Context, StateKey
from aurora_tools.execution import ToolExecutionError, ToolInstance, ToolSpec

from .plugins.self_control._meta import (
    AUTONOMY,
    CANCEL,
    CLEAN,
    COMPONENT,
    EXECUTE,
    FINISH,
    LIST,
    PREPARE,
    SCHEDULE,
    START,
    STATUS,
    self_control_plugin,
)
from .self_control_state import MAX_WAKES, SELF_CONTROL, initial_state, validate_state

CONTRACTS = {
    name: json.loads(
        files("aurora_bot").joinpath("plugins/self_control/" + name + ".schema.json").read_text(encoding="utf-8")
    )
    for name in ["status", "autonomy", "finish", "schedule", "list", "cancel"]
}

logger = logging.getLogger(__name__)
SELF_TOOLS = {
    "status": STATUS,
    "autonomy": AUTONOMY,
    "finish": FINISH,
    "schedule": SCHEDULE,
    "list": LIST,
    "cancel": CANCEL,
}


class SelfControl:
    """只持有计划等待任务，不执行 ReAct；暂停和计划由宿主 ctx 快照持久化。

    到期计划先记 pending 再提交，恢复 pending 标为 uncertain，不自动重放。
    崩溃前未落盘的状态可能丢失，不承诺恰好一次。过期计划保留供查询和显式更新。
    """

    def __init__(
        self,
        ctx: Context,
        instance_id: str,
        runtime: AgentRuntime | None = None,
        get_agent: Callable[[], ReActAgent] | None = None,
        *,
        now: Callable[[], float] = time,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        if not instance_id:
            raise ValueError("自身控制需要 bot 实例身份")
        self.ctx, self.instance_id = ctx, instance_id
        self.runtime: AgentRuntime
        self.get_agent: Callable[[], ReActAgent]
        if runtime is not None:
            self.runtime = runtime
        if get_agent is not None:
            self.get_agent = get_agent
        self.now, self.sleep = now, sleep
        self.location = {"instance_id": instance_id}
        self._changed = asyncio.Event()
        self._accepting = False
        self._worker: asyncio.Task[None] | None = None

    def state(self) -> dict:
        try:
            value = self.ctx.get(SELF_CONTROL, location=self.location)
        except KeyError:
            return initial_state()
        validate_state(value)
        return cast(dict, value)

    def _save(self, **changes: object) -> None:
        self.ctx.set(SELF_CONTROL, {**self.state(), **changes}, location=self.location)
        self._changed.set()

    def _replace(self, item: dict, **changes: object) -> dict:
        updated = {
            **item,
            "revision": item["revision"] + 1,
            "updated_at": max(self.now(), item["updated_at"]),
            **changes,
        }
        self._save(wakes=[*(wake for wake in self.state()["wakes"] if wake["wake_id"] != item["wake_id"]), updated])
        return updated

    @plug(PREPARE)
    def prepare(self) -> None:
        for item in self.state()["wakes"]:
            if item["status"] == "pending":
                self._replace(item, status="uncertain")

    @plug(START)
    def start(self) -> None:
        if self._worker is not None:
            raise RuntimeError("计划等待任务已经启动")
        self._accepting = True
        self._worker = asyncio.create_task(self._run(), name=f"bot-wakeups-{self.instance_id}")

    def stop_accepting(self) -> None:
        self._accepting = False
        if self._worker is not None and not self._worker.done() and not self._worker.cancelling():
            self._worker.cancel()

    @plug(CLEAN)
    async def close(self) -> None:
        self.stop_accepting()
        if self._worker is not None:
            await asyncio.gather(self._worker, return_exceptions=True)
            self._worker = None

    def paused(self) -> bool:
        return self.state()["paused"]

    def _previous(self, wake_id: str, revision: int) -> dict | None:
        previous = next((item for item in self.state()["wakes"] if item["wake_id"] == wake_id), None)
        actual = 0 if previous is None else previous["revision"]
        if actual != revision:
            raise ToolExecutionError("wake_conflict", "计划版本已变化，请先查询", value={"revision": actual})
        return previous

    def schedule(self, values: dict, request: ExecutionRequest, call_id: str) -> dict:
        ConfigSchema(CONTRACTS["schedule"]["parameters"]).validate(values)
        previous = self._previous(values["wake_id"], values["expected_revision"])
        if previous is not None and previous["status"] in ("pending", "uncertain"):
            raise ToolExecutionError("wake_uncertain", "投递结果未明确，须核对并显式取消，不能覆盖或重投")
        now = self.now()
        if "at" in values:
            instant = datetime.fromisoformat(values["at"])
            if instant.tzinfo is None or instant.utcoffset() is None:
                raise ValueError("at 必须包含时区")
            due = instant.timestamp()
        else:
            due = now + values["delay_seconds"]
        late = values.get("late_seconds", 3600)
        if not math.isfinite(due) or not now < due <= now + 2592000 or not math.isfinite(late):
            raise ValueError("唤醒时间必须在未来30天内，迟到有效期必须有限")
        wakes = self.state()["wakes"]
        if previous is None and len(wakes) >= MAX_WAKES:
            raise ToolExecutionError("wakes_full", "计划容量已满，请显式更新已有计划")
        item = {
            "wake_id": values["wake_id"],
            "revision": values["expected_revision"] + 1,
            "text": values["text"],
            "due_at": due,
            "expires_at": due + late,
            "created_at": now if previous is None else previous["created_at"],
            "updated_at": now if previous is None else max(now, previous["updated_at"]),
            "status": "scheduled",
            "receipt": None,
            "writer": {"run_id": request.run_id, "execution_id": request.execution_id, "call_id": call_id},
        }
        self._save(wakes=[*(wake for wake in wakes if wake["wake_id"] != item["wake_id"]), item])
        return item

    def execute(self, action: str, values: dict, request: ExecutionRequest, call_id: str) -> dict:
        values = {
            key: int(value)
            if key in ("expected_revision", "limit") and type(value) is float and value.is_integer()
            else value
            for key, value in values.items()
        }
        ConfigSchema(CONTRACTS[action]["parameters"]).validate(values)
        if action == "schedule":
            return self.schedule(values, request, call_id)
        if action == "finish":
            if not self.get_agent().request_finish(request.run_id):
                raise ToolExecutionError("run_not_active", "当前调用不属于可结束的活动运行")
            return {"run_id": request.run_id, "finish_requested": True}
        if action == "autonomy":
            self._save(paused=values["paused"])
        if action == "cancel":
            item = self._previous(values["wake_id"], values["expected_revision"])
            if item is None:
                raise ToolExecutionError("wake_not_found", "当前实例没有此计划")
            if item["status"] in ("submitted", "pending"):
                raise ToolExecutionError("wake_already_submitted", "投递已经开始，取消计划不能撤销已接纳引导")
            return self._replace(item, status="cancelled")
        state = self.state()
        if action == "list":
            items = sorted(
                (item for item in state["wakes"] if item["wake_id"] > values.get("after", "")),
                key=lambda item: item["wake_id"],
            )
            limit = values.get("limit", 10)
            page = items[:limit]
            return {"items": page, "next_after": page[-1]["wake_id"] if len(items) > limit else None}
        current = self.runtime.current
        return {
            "paused": state["paused"],
            "error": state["error"],
            "now": datetime.fromtimestamp(self.now(), UTC).isoformat(),
            "run_id": None if current is None else current.run_id,
            "next_due_at": min(
                (item["due_at"] for item in state["wakes"] if item["status"] == "scheduled"), default=None
            ),
            "counts": {
                status: sum(item["status"] == status for item in state["wakes"])
                for status in ("scheduled", "submitted", "cancelled", "expired", "uncertain", "pending")
            },
        }

    async def _wait(self, delay: float | None) -> None:
        if delay is None:
            await self._changed.wait()
            return
        tasks = [asyncio.create_task(self.sleep(min(delay, 60))), asyncio.create_task(self._changed.wait())]
        try:
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _deliver(self, item: dict) -> None:
        pending = self._replace(item, status="pending")
        try:
            receipt = self.runtime.submit(
                {
                    "kind": "planned_wakeup",
                    "wake_id": item["wake_id"],
                    "revision": item["revision"],
                    "due_at": item["due_at"],
                    "text": item["text"],
                    "notice": "这是此前登记的一次性计划，请结合当前事实判断；不证明旧动作未执行，不自动重试未知结果。",
                }
            )
        except AgentBusyError:
            self._replace(pending, status="scheduled")
            current = self.runtime.current
            if current is None:
                await self._wait(1)
            else:
                await current.wait()
            return
        except Exception:  # noqa: BLE001 - 提交可能已接纳，保留待核对记录。
            self._replace(pending, status="uncertain")
            return
        try:
            self._replace(
                pending,
                status="submitted",
                receipt={
                    "guidance_id": receipt.guidance_id,
                    "sequence": receipt.sequence,
                    "run_id": receipt.run.run_id,
                },
            )
        except Exception:
            self._replace(pending, status="uncertain")
            raise

    async def _run(self) -> None:
        try:
            while self._accepting:
                self._changed.clear()
                state = self.state()
                scheduled = sorted(
                    (item for item in state["wakes"] if item["status"] == "scheduled"),
                    key=lambda item: (item["due_at"], item["wake_id"]),
                )
                if state["paused"] or state["error"] is not None or not scheduled:
                    await self._wait(None)
                    continue
                item = scheduled[0]
                now = self.now()
                if now >= item["expires_at"]:
                    self._replace(item, status="expired")
                elif now >= item["due_at"]:
                    await self._deliver(item)
                    await asyncio.sleep(0)
                else:
                    await self._wait(item["due_at"] - now)
        except asyncio.CancelledError:
            return
        except Exception as error:  # noqa: BLE001 - 后台错误转为持久诊断，不启动自动重试。
            logger.error("计划唤醒已停止：%s", type(error).__name__)
            self._save(error="WakeupFailed")


class BoundTool:
    """执行已选择的产品工具，借用装配显式提供的服务。"""

    def __init__(self, ctx, input_state, output_state, service, action=None):
        self.ctx, self.input_state, self.output_state = ctx, input_state, output_state
        self.service, self.action = service, action

    @plug(EXECUTE)
    async def execute(self, request: ExecutionRequest) -> None:
        call = cast(dict, self.input_state.get(self.ctx, request))
        try:
            result = self.service.execute(self.action, call["arguments"], request, call["id"])
        except ValueError as error:
            raise ToolExecutionError("invalid_control", str(error)) from None
        self.output_state.set(self.ctx, request, result)


async def create_tool(action, *, ctx, storage, instance_id, input_state, output_state, owner, resources, config):
    tool = BoundTool(ctx, input_state, output_state, resources["control"], action)
    return ToolInstance(
        ExecutionPlug(COMPONENT, tool.execute, {"input": input_state, "output": output_state}, instance_id=instance_id)
    )


def _bind(instance, resources):
    instance.runtime = resources["runtime"]
    instance.get_agent = lambda: resources["agent"]


def plugin():
    return self_control_plugin(
        targets={
            SELF_CONTROL: StateKey(validate_state),
            COMPONENT: BoundTool,
            EXECUTE: BoundTool.execute,
            **{
                identity: ToolSpec(COMPONENT, CONTRACTS[action], factory=partial(create_tool, action))
                for action, identity in SELF_TOOLS.items()
            },
        },
        components={
            "control": ComponentFactory(
                lambda ctx, options: SelfControl(ctx, options["owner"]),
                lambda instance: InstanceExport(
                    plugs={PREPARE: instance.prepare, START: instance.start, CLEAN: instance.close},
                    resources={"control": instance},
                    stop_accepting=instance.stop_accepting,
                ),
                plugs=(SelfControl.prepare, SelfControl.start, SelfControl.close),
                bind=_bind,
            )
        },
    )

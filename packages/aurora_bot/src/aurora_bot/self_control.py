"""实例隔离的计划唤醒与自身运行工具；所有引导仍由既有 AgentRuntime 接纳。"""

import asyncio
import logging
import math
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from time import time
from typing import cast

from aurora_adapter.model import JsonValue
from aurora_agent.react import AgentBusyError, ReActAgent
from aurora_agent.runtime import AgentRuntime
from aurora_agent.tools import TOOLS, ToolExecutionError, ToolInstance, ToolSpec
from aurora_config import ConfigSchema
from aurora_control import ExecutionPlug, ExecutionRequest, StateBinding, component_entries
from aurora_core import Id
from aurora_core.ctx import Context, StateKey
from aurora_core.registry import RegistryEntry

from .assembly_config import WORK
from .self_control_state import MAX_WAKES, REVISION, SELF_CONTROL, WAKE_ID, initial_state, validate_state

logger = logging.getLogger(__name__)
COMPONENT = Id("org.aurora.bot:components/self_control")
SELF_TOOLS = {
    name: Id(f"org.aurora.bot:tools/self_control/{name}")
    for name in ("status", "autonomy", "finish", "schedule", "list", "cancel")
}


def _parameters(fields: dict, required: list[str]) -> dict:
    return {"type": "object", "additionalProperties": False, "properties": fields, "required": required}


_SCHEDULE = _parameters(
    {
        "wake_id": WAKE_ID,
        "expected_revision": REVISION,
        "text": {"type": "string", "minLength": 1, "maxLength": 4000},
        "delay_seconds": {"type": "number", "exclusiveMinimum": 0, "maximum": 2592000},
        "at": {"type": "string", "minLength": 1, "maxLength": 64},
        "late_seconds": {"type": "number", "exclusiveMinimum": 0, "maximum": 86400},
    },
    ["wake_id", "expected_revision", "text"],
)
_SCHEDULE["oneOf"] = [{"required": ["delay_seconds"]}, {"required": ["at"]}]
_TOOLS = {
    "status": ("bot_status", "读取自己的运行、自动引导开关、计划数量、下次唤醒及当前 UTC 时间。", _parameters({}, [])),
    "autonomy": (
        "bot_autonomy",
        "设置 paused。暂停普通 cadence 和计划唤醒，保留计划且直接交流仍可用；false 恢复。不会结束当前运行或清除故障。",
        _parameters({"paused": {"type": "boolean"}}, ["paused"]),
    ),
    "finish": (
        "bot_finish",
        "请求本轮全部工具和结果观察完成后正常结束，不再推理。应放在本批最后；不取消其他工具或新输入，不暂停自动引导。",
        _parameters({}, []),
    ),
    "schedule": (
        "wake_schedule",
        (
            "创建或更新一次性唤醒。用 delay_seconds 或带时区的 ISO 时间 at，二选一，最多30天后。"
            "late_seconds 为迟到有效期，默认3600秒；过期不补发。创建 expected_revision=0，更新先查询版本。"
            "仅提交未来引导，不重试旧工具。工具成功表示已写入 ctx，宿主异步落盘。"
        ),
        _SCHEDULE,
    ),
    "list": (
        "wake_list",
        "分页读取自己的完整唤醒计划和投递回执。uncertain 须核对，不能据缺失回执推断未执行或自动重试。",
        _parameters(
            {"after": {"type": "string", "maxLength": 64}, "limit": {"type": "integer", "minimum": 1, "maximum": 20}},
            [],
        ),
    ),
    "cancel": (
        "wake_cancel",
        "按当前 revision 取消未提交计划。uncertain 仅停止后续投递，不撤销可能已接纳的引导；先核对外部结果。",
        _parameters({"wake_id": WAKE_ID, "expected_revision": REVISION}, ["wake_id", "expected_revision"]),
    ),
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
        runtime: AgentRuntime,
        get_agent: Callable[[], ReActAgent],
        *,
        now: Callable[[], float] = time,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        if not instance_id:
            raise ValueError("自身控制需要 bot 实例身份")
        self.ctx, self.instance_id, self.runtime, self.get_agent = ctx, instance_id, runtime, get_agent
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

    def prepare(self) -> None:
        for item in self.state()["wakes"]:
            if item["status"] == "pending":
                self._replace(item, status="uncertain")

    def start(self) -> None:
        if self._worker is not None:
            raise RuntimeError("计划等待任务已经启动")
        self._accepting = True
        self._worker = asyncio.create_task(self._run(), name=f"bot-wakeups-{self.instance_id}")

    def stop_accepting(self) -> None:
        self._accepting = False
        if self._worker is not None and not self._worker.done() and not self._worker.cancelling():
            self._worker.cancel()

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
        ConfigSchema(_SCHEDULE).validate(values)
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
        ConfigSchema(_TOOLS[action][2]).validate(values)
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


async def _declared(request: ExecutionRequest) -> None:
    raise RuntimeError("自身控制工具需要默认装配注入实例服务")


async def create_tool(
    action,
    *,
    service: SelfControl,
    ctx,
    storage,
    instance_id,
    input_state: StateBinding,
    output_state: StateBinding,
    config,
) -> ToolInstance:
    if (
        config
        or ctx is not service.ctx
        or any(
            binding.key != WORK or dict(binding.location).get("instance_id") != service.instance_id
            for binding in (input_state, output_state)
        )
    ):
        raise ValueError("自身控制工具必须绑定同一 bot，不接受所有者覆盖")

    async def execute(request: ExecutionRequest) -> None:
        call = cast(dict, input_state.get(ctx, request))
        try:
            result = service.execute(action, call["arguments"], request, call["id"])
        except ValueError as error:
            raise ToolExecutionError("invalid_control", str(error)) from None
        output_state.set(ctx, request, result)

    return ToolInstance(
        ExecutionPlug(COMPONENT, execute, {"input": input_state, "output": output_state}, instance_id=instance_id)
    )


def entries() -> tuple[RegistryEntry, ...]:
    return (
        RegistryEntry(SELF_CONTROL, "state_key", StateKey(validate_state), "aurora_bot"),
        *component_entries(COMPONENT, SelfControl, _declared, provider="aurora_bot"),
        *(
            RegistryEntry(
                SELF_TOOLS[action],
                "tool",
                ToolSpec(
                    COMPONENT,
                    {"name": name, "description": description, "parameters": cast(dict[str, JsonValue], parameters)},
                ),
                "aurora_bot",
                register_to=TOOLS,
            )
            for action, (name, description, parameters) in _TOOLS.items()
        ),
    )

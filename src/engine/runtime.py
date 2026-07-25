"""完整拥有 Agent pump 热路径的运行时引擎。"""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import asdict
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from src.contracts.agent import AgentHandler, CapabilityCatalogSnapshot, EngineConfiguration
from src.contracts.amp import AmpEnvelope
from src.contracts.model import ModelRequest
from src.engine.state import EngineState, PumpResult
from src.engine.tool_registry import ToolRegistry
from src.utils.logging import get_logger

if TYPE_CHECKING:
    from src.contracts.memory import MemoryStore
    from src.contracts.model import ModelProvider
    from src.contracts.tool import ToolExecutorBinding


class _Msg(StrEnum):
    """本文件内所有用户可见或日志输出的字符串常量。"""

    RESERVED_EVENT_TYPE = "reserved internal event type: {amp_type}"


logger = get_logger("aurora.engine.runtime")


class AgentEngine:
    """组合持久化状态、模型、工具与自动记忆服务的完整 Agent 引擎。"""

    def __init__(
        self,
        configuration: EngineConfiguration,
        handlers: dict[str, AgentHandler],
        *,
        model_provider: ModelProvider,
        memory_store: MemoryStore | None = None,
        idle_wait_seconds: float = 1.0,
    ) -> None:
        self.configuration = configuration
        self._state = EngineState(configuration, handlers, memory_store)
        self._model_provider = model_provider
        self._memory_store = memory_store
        self._idle_wait_seconds = idle_wait_seconds
        self._tools = ToolRegistry(self._state, self._state)
        self._pump_lock = asyncio.Lock()
        self._shutdown_lock = asyncio.Lock()
        self._closed = False
        self._model_dispatch_task: asyncio.Task[None] | None = None
        self._model_activity_tasks: dict[asyncio.Task[None], str] = {}
        self._wake = asyncio.Event()

    def bind_tool_executors(self, bindings: tuple[ToolExecutorBinding, ...]) -> None:
        """安装进程组合根提供的不可变工具执行目录。"""
        catalog = self._tools.bind(bindings)
        self._state.install_capability_catalog(CapabilityCatalogSnapshot(catalog.capabilities))

    async def submit_amp(self, value: object) -> str:
        """解析并提交外部 AMP，同时中断受外部活动影响的自主模型调用。"""
        amp = AmpEnvelope.parse(value)
        if amp.payload.type in {"tool.succeeded", "tool.failed", "tool.unknown"}:
            raise ValueError(_Msg.RESERVED_EVENT_TYPE.format(amp_type=amp.payload.type))
        if amp.payload.type != "system.tick":
            cancelled = set(await self._state.cancel_autonomous_tasks("external_activity"))
            for task, task_id in tuple(self._model_activity_tasks.items()):
                if task_id in cancelled:
                    task.cancel()
        await self._state.submit_amp(amp)
        self._wake.set()
        return amp.header.message_id

    async def pump(self, max_turns: int | None = None) -> dict[str, Any]:
        """执行工具恢复、Agent turn、工具/模型派发和自动记忆 hook。"""
        async with self._pump_lock:
            recoveries = await self._tools.recover_pending()
            result: PumpResult = await self._state.pump(max_turns)
            receipts = await self._tools.execute_pending()
            self._ensure_model_dispatcher()
            if self._memory_store is not None:
                for entry in self._state.completed_memory_entries():
                    try:
                        await asyncio.to_thread(self._memory_store.remember, entry)
                    except Exception as error:
                        logger.warning(
                            "Memory remember failed task_id=%s error_type=%s", entry.task_id, type(error).__name__
                        )
            response = asdict(result)
            response["tool_recovery_receipts_emitted"] = recoveries
            response["tool_receipts_emitted"] = receipts
            return response

    async def run_forever(self, stop_event: asyncio.Event | None = None) -> None:
        """持续推进 engine；无工作时等待输入唤醒。"""
        stop = stop_event or asyncio.Event()
        while not stop.is_set():
            if self._state.has_work():
                await self.pump()
                continue
            if self._state.has_pending_model_requests():
                self._ensure_model_dispatcher()
            self._wake.clear()
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._wake.wait(), timeout=self._idle_wait_seconds)

    def _ensure_model_dispatcher(self) -> None:
        """确保模型 Activity 分发任务已启动。"""
        if self._model_dispatch_task is None or self._model_dispatch_task.done():
            self._model_dispatch_task = asyncio.create_task(self._dispatch_models(), name="aurora-model-activities")

    async def _dispatch_models(self) -> None:
        """认领并发执行模型 Activity，直到队列为空。"""
        while True:
            activities = await self._state.claim_model_requests(self._state.limits.model_concurrency)
            if not activities:
                return
            tasks = []
            for activity in activities:
                task = asyncio.create_task(self._execute_model(activity), name=f"aurora-model-{activity.activity_id}")
                self._model_activity_tasks[task] = activity.task_id
                task.add_done_callback(self._model_activity_tasks.pop)
                tasks.append(task)
            await asyncio.gather(*tasks, return_exceptions=True)
            self._wake.set()

    async def _execute_model(self, activity: Any) -> None:
        """通过注入的模型 Port 执行单个 Activity 并记录结果。"""
        task = self._state.get_task(activity.task_id)
        if task is None or task.terminal:
            return
        try:
            result = await self._model_provider.complete(ModelRequest.from_dict(activity.request))
        except asyncio.CancelledError:
            await self._state.complete_model(activity, None, "cancelled:external_activity")
            raise
        except Exception as error:
            await self._state.complete_model(activity, None, f"{type(error).__name__}: {error}")
            return
        await self._state.complete_model(activity, result.to_dict(), None)

    async def shutdown(self) -> None:
        """取消模型任务并关闭持久化状态资源。"""
        async with self._shutdown_lock:
            if self._closed:
                return
            self._closed = True
            if self._model_dispatch_task is not None:
                self._model_dispatch_task.cancel()
            for task in tuple(self._model_activity_tasks):
                task.cancel()
            pending = tuple(self._model_activity_tasks)
            if self._model_dispatch_task is not None:
                pending = (*pending, self._model_dispatch_task)
            await asyncio.gather(*pending, return_exceptions=True)
            self._state.shutdown()

    def status(self) -> dict[str, Any]:
        """返回 engine 状态与模型分发统计。"""
        return {
            **self._state.status(),
            "model_dispatch_active": self._model_dispatch_task is not None and not self._model_dispatch_task.done(),
            "active_model_activities": len(self._model_activity_tasks),
        }

    def task_detail(self, task_id: str) -> dict[str, Any] | None:
        return self._state.task_detail(task_id)

    def agent_detail(self, agent_id: str) -> dict[str, Any] | None:
        return self._state.agent_detail(agent_id)

    def brain_context(self) -> dict[str, Any]:
        return self._state.brain_context().to_dict()

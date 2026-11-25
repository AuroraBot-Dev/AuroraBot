"""Agent 的单一调度所有者；提交、等待与取消均限宿主事件循环。"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal
from uuid import uuid4

from aurora_adapter.model import JsonValue
from aurora_control import ExecutionRequest
from aurora_core.json_data import encode_json

from .react import AgentBusyError, ReActAgent

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RunResult:
    """运行句柄的终态；error 仅保存异常类型，不持有任务或供应商对象。"""

    run_id: str
    status: Literal["completed", "cancelled", "failed"]
    error: str | None = None


class RunHandle:
    """等待不会传播取消到 agent；显式取消必须通过 AgentRuntime.cancel(run_id)。"""

    def __init__(self) -> None:
        self._request = ExecutionRequest(uuid4().hex)
        self._completion: asyncio.Future[RunResult] = asyncio.get_running_loop().create_future()
        self._task: asyncio.Task[None] | None = None
        self._cancel_requested = False

    @property
    def run_id(self) -> str:
        return self._request.run_id

    @property
    def done(self) -> bool:
        return self._completion.done()

    async def wait(self) -> RunResult:
        if self._task is asyncio.current_task():
            raise RuntimeError("激活不能等待自身结束")
        return await asyncio.shield(self._completion)

    def _cancel(self) -> None:
        if not self.done and not self._cancel_requested:
            self._cancel_requested = True
            if self._task is not None and not self._task.done():
                self._task.cancel()

    def _finish(self, result: RunResult) -> None:
        if not self.done:
            self._completion.set_result(result)
        self._task = None


@dataclass(frozen=True)
class Submission:
    """引导已写入 inbox 的回执；sequence 表示接纳顺序，不表示业务完成。"""

    sequence: int
    guidance_id: str
    run: RunHandle


class AgentRuntime:
    """每个 agent 由一个管理器串行调度，启动时不自动激活恢复的输入。

    submit 自动生成引导身份和下一序号；显式 sequence 须大于 progress 与 inbox 中的
    全部序号，重复或过期提交在写入前拒绝。相同文本配合新序号表示新的引导。
    同一激活的输入共享句柄；finish 阶段及终态通知期间的输入取得下一次激活句柄。
    成功后复查 pending；失败或取消停止后续调度，未消费输入保留到显式 activate/submit。
    等候中的后续句柄以 failed/PreviousRunFailed 或 cancelled 收束，不自动重试。
    运行句柄仅存在于进程内；可恢复数据沿用 agent 的 inbox/progress/runtime。
    get_agent 在宿主完成装配后提供同一实例，execute 等待激活及清理完成，is_executing
    覆盖显式激活与清理期间的占用。宿主须在 start 前完成装配、close 后再释放资源。
    """

    def __init__(
        self,
        *,
        get_agent: Callable[[], ReActAgent],
        execute: Callable[[ExecutionRequest], Awaitable[None]],
        is_executing: Callable[[], bool],
    ) -> None:
        self._get_agent = get_agent
        self._activate = execute
        self._is_executing = is_executing
        self._loop: asyncio.AbstractEventLoop | None = None
        self._accepting = False
        self._writing = False
        self._current: RunHandle | None = None
        self._queued: RunHandle | None = None
        self._worker: asyncio.Task[None] | None = None

    @property
    def current(self) -> RunHandle | None:
        return self._current

    def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._accepting = True

    def _check_loop(self) -> None:
        if asyncio.get_running_loop() is not self._loop:
            raise RuntimeError("运行管理入口必须在启动它的宿主事件循环调用")

    def _check_accepting(self) -> None:
        self._check_loop()
        if not self._accepting:
            raise RuntimeError("agent 未启动或正在关闭")
        if self._writing:
            raise RuntimeError("inbox 写入通知期间不能重入提交，请调度到下一事件循环轮次")
        if self._is_executing() and self._current is None:
            raise AgentBusyError("显式激活正在执行，不能混用调度所有者")
        if any(handle is not None and handle._cancel_requested for handle in (self._current, self._queued)):
            raise AgentBusyError("当前激活正在取消，请等待清理完成")

    def _finishing(self, handle: RunHandle) -> bool:
        agent = self._get_agent()
        try:
            state = agent.runtime.get(agent.ctx, handle._request)
        except KeyError:
            return False
        return (
            isinstance(state, dict)
            and state.get("run_id") == handle.run_id
            and (state.get("phase") == "finish" or state.get("status") != "running")
        )

    def _reserve(self) -> RunHandle:
        if self._current is None:
            self._current = RunHandle()
        if self._finishing(self._current):
            if self._queued is None:
                self._queued = RunHandle()
            return self._queued
        return self._current

    def _schedule(self) -> None:
        if not self._accepting:
            self.stop_accepting()
        if self._worker is None:
            self._worker = asyncio.create_task(self._drive(), name="aurora-agent-runtime")

    def activate(self) -> RunHandle:
        """显式激活已有输入，也允许没有新输入；活动阶段的重复激活返回同一句柄。"""
        self._check_accepting()
        handle = self._reserve()
        self._schedule()
        return handle

    def submit(self, payload: JsonValue, *, sequence: int | None = None) -> Submission:
        """同步写入引导并返回句柄；调用方持有序号时可明确拒绝重放。"""
        self._check_accepting()
        encode_json(payload)
        agent = self._get_agent()
        request = ExecutionRequest("submission")
        pending = agent.pending(request)
        try:
            progress = agent.progress.get(agent.ctx, request)
        except KeyError:
            progress = 0
        assert isinstance(progress, int)
        latest = max(progress, pending[-1]["sequence"] if pending else 0)
        if sequence is None:
            sequence = latest + 1
        if type(sequence) is not int or sequence <= latest:
            raise ValueError("引导序号必须为大于已接纳序号的整数，重复或过期提交被拒绝")
        identity = uuid4().hex
        self._writing = True
        try:
            agent.inbox.set(agent.ctx, request, [*pending, {"id": identity, "sequence": sequence, "payload": payload}])
        finally:
            self._writing = False
        handle = self._reserve()
        self._schedule()
        return Submission(sequence, identity, handle)

    async def _execute(self, handle: RunHandle) -> RunResult:
        if handle._cancel_requested:
            return RunResult(handle.run_id, "cancelled")

        async def activate() -> None:
            await self._activate(handle._request)

        handle._task = asyncio.create_task(activate(), name=f"agent-{handle.run_id}")
        try:
            await handle._task
        except asyncio.CancelledError:
            return RunResult(handle.run_id, "cancelled")
        except Exception as error:  # noqa: BLE001 - 后台激活异常转换为明确终态，宿主仍可接收下一次显式激活。
            logger.error("agent 激活失败：%s", type(error).__name__)
            return RunResult(handle.run_id, "failed", type(error).__name__)
        return RunResult(handle.run_id, "completed")

    async def _drive(self) -> None:
        try:
            while self._current is not None:
                handle = self._current
                result = await self._execute(handle)
                handle._finish(result)
                self._current, self._queued = self._queued, None
                if result.status != "completed" or not self._accepting:
                    if self._current is not None:
                        failed = result.status == "failed"
                        self._current._finish(
                            RunResult(
                                self._current.run_id,
                                "failed" if failed else "cancelled",
                                "PreviousRunFailed" if failed else None,
                            )
                        )
                        self._current = None
                elif self._current is None:
                    agent = self._get_agent()
                    if agent.pending(handle._request):
                        self._current = RunHandle()
        except Exception as error:  # noqa: BLE001 - 调度失败结束全部回执并保留未消费输入。
            logger.error("agent 调度失败：%s", type(error).__name__)
        finally:
            # 调度本身异常时也结束回执，避免等待者悬挂；剩余输入仍在 inbox。
            for handle in (self._current, self._queued):
                if handle is not None:
                    handle._finish(RunResult(handle.run_id, "failed", "SchedulerStopped"))
            self._current = self._queued = None
            self._worker = None

    async def cancel(self, run_id: str) -> bool:
        """取消匹配的在途或待执行激活并等待清理；未知或已终结的身份返回 False。"""
        self._check_loop()
        handle = next((item for item in (self._current, self._queued) if item and item.run_id == run_id), None)
        if handle is None or handle.done:
            return False
        if handle._task is asyncio.current_task():
            raise RuntimeError("激活不能等待自身取消")
        if handle is self._current and self._finishing(handle):
            agent = self._get_agent()
            state = agent.runtime.get(agent.ctx, handle._request)
            if isinstance(state, dict) and state.get("status") != "running":
                await handle.wait()
                return False
        handle._cancel()
        if handle is self._queued:
            handle._finish(RunResult(handle.run_id, "cancelled"))
            # 保留取消标记直到调度者复查，防止本轮 pending 复查重新启动该输入。
        await handle.wait()
        return True

    def stop_accepting(self) -> None:
        self._accepting = False
        for handle in (self._current, self._queued):
            if handle is not None:
                handle._cancel()

    async def close(self) -> None:
        """关闭入口并等待自有任务；等待者取消不打断资源收尾。"""
        if self._current is not None and self._current._task is asyncio.current_task():
            raise RuntimeError("激活不能等待自身关闭")
        self.stop_accepting()
        if self._worker is not None:
            await asyncio.shield(self._worker)

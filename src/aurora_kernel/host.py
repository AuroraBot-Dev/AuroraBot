"""通用宿主：一次解析决定 namespace、调用点、阶段顺序和资源释放。"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from aurora_kernel.calls import Calls, invoke, invoke_sync
from aurora_kernel.context import Context
from aurora_kernel.declaration import ModuleSpec, Namespace
from aurora_kernel.failures import ModuleCleanup, collect_failure
from aurora_kernel.lifecycle import ManagedAssembly
from aurora_kernel.phase import CLOSE, CONSTRUCTION_KINDS, PhaseKind
from aurora_kernel.resolve import resolve
from aurora_kernel.tasks import raise_with_cleanup, wait_for_completion

if TYPE_CHECKING:
    from collections.abc import Iterable


class Host:
    """每个宿主拥有自己的上下文；注册声明可以安全复用于多个宿主。"""

    def __init__(self, modules: Iterable[Namespace | ModuleSpec], *, ctx: Context | None = None) -> None:
        specs = tuple(item.spec if isinstance(item, Namespace) else item for item in modules)
        self.resolution = resolve(specs)
        active = self.resolution.construction
        self._calls = Calls(active)
        self.ctx = ctx if ctx is not None else Context()
        if self.ctx._host is not None:
            raise ValueError("同一个 ctx 只能绑定一个宿主")
        for spec in active:
            self.ctx.ensure(spec.module_id)
        self.ctx._host = self
        self._constructed = False
        self._claimed = False
        self._lifecycle: ManagedAssembly | None = None

    def call(self, target: str, *args: Any, **kwargs: Any) -> Any:
        self._require_ready()
        return self._calls.call(self.ctx, target, *args, **kwargs)

    async def acall(self, target: str, *args: Any, **kwargs: Any) -> Any:
        self._require_ready()
        return await self._calls.acall(self.ctx, target, *args, **kwargs)

    def build(self) -> Host:
        """只执行同步构造；异步资源必须通过 prepare 管理。"""
        self._claim()
        for step in self.resolution.phases:
            if step.phase.kind is not PhaseKind.BUILD:
                continue
            for spec in step.modules:
                if hook := spec.hook(step.phase):
                    invoke_sync(self.ctx, spec.module_id, hook)
        self._constructed = True
        return self

    async def prepare(self) -> ManagedAssembly:
        """准备和构造失败时释放已成功获得的全部资源。"""
        self._claim()
        cleanups: list[ModuleCleanup] = []
        constructed: list[ModuleSpec] = []
        try:
            for step in self.resolution.phases:
                if step.phase.kind not in CONSTRUCTION_KINDS:
                    continue
                for spec in step.modules:
                    hook = spec.hook(step.phase)
                    if hook is None:
                        continue
                    if step.phase.kind is PhaseKind.SETUP:
                        cleanup = await invoke(self.ctx, spec.module_id, hook)
                        if cleanup is not None:
                            if not callable(cleanup):
                                raise TypeError(f"准备钩子必须返回清理函数或 None：{spec.module_id}")
                            cleanups.append(ModuleCleanup(spec.module_id, step.phase.name, cleanup))
                    else:
                        invoke_sync(self.ctx, spec.module_id, hook)
                        constructed.append(spec)
        except BaseException as error:
            logging.getLogger(__name__).exception("宿主构造失败，开始释放已获得的资源")
            rollback = asyncio.create_task(self._rollback(constructed, cleanups), name="kernel:rollback")
            failures, interrupted = await wait_for_completion(rollback)
            raise_with_cleanup(error, failures, interrupted)
        self._constructed = True
        self._lifecycle = ManagedAssembly(self, self.ctx, self.resolution, tuple(cleanups))
        return self._lifecycle

    def _claim(self) -> None:
        if self._claimed:
            raise RuntimeError("宿主只能构造一次")
        self._claimed = True

    def _require_ready(self) -> None:
        if not self._constructed:
            raise RuntimeError("调用前必须先构造宿主")
        if self._lifecycle is not None and self._lifecycle.closed:
            raise RuntimeError("宿主已关闭")

    async def _rollback(self, constructed: list[ModuleSpec], cleanups: list[ModuleCleanup]) -> list[Exception]:
        failures: list[Exception] = []
        closed: set[str] = set()
        for spec in reversed(constructed):
            if spec.module_id in closed:
                continue
            closed.add(spec.module_id)
            if hook := spec.hook(CLOSE):
                failure = await collect_failure(spec.module_id, CLOSE.name, invoke(self.ctx, spec.module_id, hook))
                if failure is not None:
                    failures.append(failure)
        for cleanup in reversed(cleanups):
            if failure := await cleanup.run():
                failures.append(failure)
        return failures

"""串行、分支、条件循环与并行组件；业务结果由各实例写回 ctx。"""

import asyncio
from collections.abc import Callable

from aurora_core.ctx import Context
from aurora_core.ids import Id

from .execution import CONTROL_STATE, ExecutionLink, ExecutionPlug, ExecutionRequest, ExecutionSlot


class Controller:
    """可嵌套的控制组件；在途状态按实例、运行和执行身份独立保存。

    组件不持有后台任务；宿主应通过 Lifecycle.run 等待根调用，关闭时等待或取消。
    终态通过 ctx.subscribe 观察，随后删除本次状态；调用等待决定完成，不保留调用历史。
    """

    definition_id = Id("org.aurora.control:handlers/control")

    def __init__(self, ctx: Context, slot: ExecutionSlot) -> None:
        if slot.definition_id != self.definition_id:
            raise ValueError(f"组件与插槽定义不符：{self.definition_id} / {slot.definition_id}")
        self.ctx = ctx
        self.slot = slot

    @property
    def plug(self) -> ExecutionPlug:
        return ExecutionPlug(
            self.definition_id, self.execute, self.slot.states, self.slot.schema, instance_id=self.slot.instance_id
        )

    def _location(self, request: ExecutionRequest) -> dict[str, str]:
        return {
            "definition_id": str(self.definition_id),
            "instance_id": self.slot.instance_id,
            "run_id": request.run_id,
            "execution_id": request.execution_id,
        }

    def _update(self, request: ExecutionRequest, **changes: object) -> None:
        location = self._location(request)
        record = self.ctx.get(CONTROL_STATE, location=location)
        assert isinstance(record, dict)
        self.ctx.set(CONTROL_STATE, {**record, **changes}, location=location)

    async def execute(self, request: ExecutionRequest) -> None:
        """发布 running 与终态后清理本次状态；异常与取消继续传播给调用方。"""
        self.ctx.set(
            CONTROL_STATE,
            {"status": "running", "parent_execution_id": request.parent_execution_id},
            location=self._location(request),
        )
        try:
            await self._run(request)
        except asyncio.CancelledError:
            self._update(request, status="cancelled")
            raise
        except Exception:
            self._update(request, status="failed")
            raise
        else:
            self._update(request, status="completed")
        finally:
            self.ctx.delete(CONTROL_STATE, location=self._location(request))

    async def _invoke(self, link: ExecutionLink, request: ExecutionRequest) -> None:
        await self.slot.invoke(link, request.child())

    async def _run(self, request: ExecutionRequest) -> None:
        raise NotImplementedError


class Serial(Controller):
    """按连接顺序等待子组件，失败或取消立即终止后续调用。"""

    definition_id = Id("org.aurora.control:handlers/control/serial")

    async def _run(self, request: ExecutionRequest) -> None:
        for link in self.slot.links():
            await self._invoke(link, request)


class Branch(Controller):
    """选择器从 ctx 读取条件并返回子实例标识；None 表示本次不执行分支。

    选择结果仅为控制信息。返回未连接实例时明确失败，不默默回退。
    """

    definition_id = Id("org.aurora.control:handlers/control/branch")

    def __init__(self, ctx: Context, slot: ExecutionSlot, select: Callable[[ExecutionRequest], str | None]) -> None:
        super().__init__(ctx, slot)
        self.select = select

    async def _run(self, request: ExecutionRequest) -> None:
        selected = self.select(request)
        self._update(request, selected=selected)
        if selected is None:
            return
        for link in self.slot.links():
            if link.plug.instance_id == selected:
                await self._invoke(link, request)
                return
        raise ValueError(f"分支未连接：{selected}")


class LoopLimitExceeded(RuntimeError):
    """条件仍为真但已用完装配指定的迭代额度。"""


class While(Controller):
    """先读取条件，再执行唯一循环体；多步循环体通过嵌套 Serial 表达。

    每次迭代完成后让出事件循环以接收取消。达到上限且仍需继续时抛出异常。
    """

    definition_id = Id("org.aurora.control:handlers/control/while")

    def __init__(
        self,
        ctx: Context,
        slot: ExecutionSlot,
        condition: Callable[[ExecutionRequest], bool],
        *,
        max_iterations: int,
    ) -> None:
        super().__init__(ctx, slot)
        if type(max_iterations) is not int or max_iterations < 1:
            raise ValueError("循环上限必须为正整数")
        self.condition = condition
        self.max_iterations = max_iterations

    async def _run(self, request: ExecutionRequest) -> None:
        links = self.slot.links()
        if len(links) != 1:
            raise ValueError("条件循环必须连接一个循环体")
        iterations = 0
        self._update(request, iterations=iterations)
        while self.condition(request):
            if iterations == self.max_iterations:
                raise LoopLimitExceeded(f"循环达到 {self.max_iterations} 次上限")
            await self._invoke(links[0], request)
            iterations += 1
            self._update(request, iterations=iterations)
            await asyncio.sleep(0)


class Parallel(Controller):
    """有界并发；任一子调用失败或取消时取消其余任务，并等待全部清理。

    异常保留最先传播到父调用的异常；并行分支的业务结果各自保存在 ctx。
    并发指宿主事件循环中的异步工作，不将同步代码移到线程。
    """

    definition_id = Id("org.aurora.control:handlers/control/parallel")

    def __init__(self, ctx: Context, slot: ExecutionSlot, *, concurrency: int) -> None:
        super().__init__(ctx, slot)
        if type(concurrency) is not int or concurrency < 1:
            raise ValueError("并发上限必须为正整数")
        self.concurrency = concurrency

    async def _run(self, request: ExecutionRequest) -> None:
        semaphore = asyncio.Semaphore(self.concurrency)

        async def invoke(link: ExecutionLink) -> None:
            async with semaphore:
                await self._invoke(link, request)

        tasks = [asyncio.create_task(invoke(link)) for link in self.slot.links()]
        try:
            await asyncio.gather(*tasks)
        except BaseException:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise

"""运行真实 aurora_kernel，逐步观察声明、调用、上下文和生命周期。

从项目根目录执行：uv run python -m playground.examples.kernel
单独运行场景：uv run python -m playground.examples.kernel context
"""

from __future__ import annotations

import argparse
import asyncio
from typing import TYPE_CHECKING

from rich.console import Console

from aurora_kernel import (
    ACTIVATE,
    CLOSE,
    DRAIN,
    PREPARE,
    READY,
    RUN,
    Change,
    Context,
    ContextConflictError,
    Host,
    ModuleSpec,
    namespace,
)
from playground.modules.kernel.fixtures import client, counter, extension

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

console = Console(highlight=False, markup=False)


def show(label: str, value: object) -> None:
    console.print(f"  {label}：{value}")


def observe(change: Change) -> None:
    fields = ", ".join(f"{name}.{key}" for name, key in change.keys)
    show(f"ctx r{change.revision} / 来源 {change.source}", fields)


def demo_hooks(amount: int) -> None:
    console.rule("hooks · 依赖排序与三种调用模式")
    modules = (client, extension, counter)
    host = Host(modules)
    show("传入顺序", " → ".join(module.name for module in modules))
    show("构造顺序", " → ".join(spec.module_id for spec in host.resolution.construction))
    show("构造前自动建立的空间", host.ctx.snapshot())
    host.build()
    unsubscribe = host.ctx.subscribe(observe)
    try:
        show("single / extension 优先级 10，counter 优先级 0", host.call("counter:increment", amount))
        show("collect / 按优先级返回元组", host.call("counter:describe"))
        show("notify / 顺序执行全部实现", host.call("counter:changed", host.ctx["counter"]["value"]))
        show("client:run / ctx.call 嵌套调用", host.call("client:run", amount))
        show("最终 ctx", host.ctx.snapshot())
    finally:
        unsubscribe()
    independent = Host(modules).build()
    show("相同声明创建另一个 Host，计数从零开始", independent.ctx["counter"]["value"])
    baseline = Host((counter,)).build()
    show("只装配 counter，使用默认 increment", baseline.call("counter:increment", amount))


def demo_context() -> None:
    console.rule("context · 容器快照、跨空间事务与冲突")
    host = Host((counter, extension)).build()
    ctx = host.ctx
    unsubscribe = ctx.subscribe(observe)
    try:
        history = ctx["counter"]["history"]
        history.append(7)
        show("修改读出的 list 后，ctx 中的 history", ctx["counter"]["history"])
        ctx["counter"]["history"] = history
        show("显式写回后", ctx["counter"]["history"])

        with ctx.bind("playground.transaction"), ctx.transaction() as staged:
            staged["counter"]["value"] = 10
            staged["extension"]["notifications"] = 1
        show("跨空间提交只产生一次变更", ctx.last_change)

        try:
            with ctx.transaction() as staged:
                staged["counter"]["value"] = 999
                raise ValueError("演示主动中止事务")
        except ValueError as error:
            show("事务异常", error)
        show("中止后 value 保持 10", ctx["counter"]["value"])

        try:
            with ctx.transaction() as staged:
                staged["counter"]["value"] = 999
                # 用一次确定性的宿主写入模拟其他调用在事务期间提交。
                with ctx.bind("playground.other_writer"):
                    ctx["extension"]["notifications"] = 2
        except ContextConflictError as error:
            show("捕获预期冲突", error)
        else:
            raise AssertionError("事务应拒绝覆盖期间发生的写入")
        show("冲突后 value 保持 10，其他写入保留", ctx.snapshot())

        service = asyncio.Event()
        ctx["extension"]["service"] = service
        show("服务对象按引用共享", ctx["extension"]["service"] is service)
        revision = ctx.revision
        ctx["extension"]["service"].set()
        show("服务内部变化不会递增 ctx.revision", ctx.revision == revision)
    finally:
        unsubscribe()


@namespace("resource")
def resource(ctx: Context) -> None:
    show("construct / resource", f"准备状态={ctx['resource']['connected']}")


@resource.on(PREPARE)
async def prepare_resource(ctx: Context) -> Callable[[], Awaitable[None]]:
    ctx["resource"]["connected"] = True
    show("prepare / resource", "取得内存资源")

    async def cleanup() -> None:
        ctx["resource"]["connected"] = False
        show("cleanup / resource", "释放准备阶段取得的资源")

    return cleanup


@resource.on(CLOSE)
def close_resource(ctx: Context) -> None:
    show("close / resource", f"清理函数执行前 connected={ctx['resource']['connected']}")


@namespace("worker", requires=("resource",))
def worker(ctx: Context) -> None:
    ctx["worker"].update(jobs=0, started=asyncio.Event(), finished=asyncio.Event(), fail_run=False)
    show("construct / worker", "依赖 resource")


@worker.on(PREPARE)
async def prepare_worker(ctx: Context) -> Callable[[], Awaitable[None]]:
    ctx["worker"]["prepared"] = True
    show("prepare / worker", "准备工作者")

    async def cleanup() -> None:
        ctx["worker"]["prepared"] = False
        show("cleanup / worker", "先于 resource 释放")

    return cleanup


@worker.on(ACTIVATE)
def activate_worker(ctx: Context) -> None:
    ctx["worker"]["active"] = True
    show("activate / worker", "激活")


@worker.on(READY)
def ready_worker(ctx: Context) -> None:
    show("ready / worker", f"active={ctx['worker']['active']}")


@worker.callpoint("ping")
async def ping(ctx: Context) -> str:
    return f"pong / jobs={ctx['worker']['jobs']}"


@worker.on(RUN)
async def run_worker(ctx: Context, stop: asyncio.Event) -> None:
    try:
        ctx["worker"]["jobs"] += 1
        show("run / worker", "后台任务已启动")
        ctx["worker"]["started"].set()
        if ctx["worker"]["fail_run"]:
            raise RuntimeError("playground 主动触发的后台故障")
        await stop.wait()
        show("run / worker", "收到停止信号")
    finally:
        ctx["worker"]["finished"].set()


@worker.on(DRAIN)
def drain_worker(ctx: Context) -> None:
    show("drain / worker", f"已处理 jobs={ctx['worker']['jobs']}")


@worker.on(CLOSE)
def close_worker(ctx: Context) -> None:
    ctx["worker"]["active"] = False
    show("close / worker", "先于 resource 关闭")


async def demo_lifecycle(*, fail_run: bool) -> None:
    console.rule("lifecycle · 准备、构造、激活、后台与逆序关闭")
    host = Host((worker, resource))
    for step in host.resolution.phases:
        show(f"计划 {step.phase.name}", " → ".join(spec.module_id for spec in step.modules) or "无回调")
    lifecycle = await host.prepare()
    stop = asyncio.Event()
    try:
        host.ctx["worker"]["fail_run"] = fail_run
        # 用事件握手保证输出顺序；超时只用于防止修改示例后无限等待。
        async with asyncio.timeout(5):
            await lifecycle.activate(stop)
            await host.ctx["worker"]["started"].wait()
            show("await host.acall", await host.acall("worker:ping"))
            if fail_run:
                show("next_failure / 宿主取走后台故障", await lifecycle.next_failure())
            stop.set()
            await host.ctx["worker"]["finished"].wait()
    finally:
        stop.set()
        await lifecycle.close()
    show("关闭后 resource.connected", host.ctx["resource"]["connected"])
    show("关闭后 worker.prepared / active", (host.ctx["worker"]["prepared"], host.ctx["worker"]["active"]))
    try:
        await host.acall("worker:ping")
    except RuntimeError as error:
        show("关闭后拒绝调用", error)
    else:
        raise AssertionError("关闭后的宿主不应接受调用")


def demo_validation() -> None:
    console.rule("validation · 在初始化之前拒绝无效声明")
    initialized: list[str] = []

    @namespace("guard")
    def guard(ctx: Context) -> None:
        initialized.append("guard")
        ctx["guard"]["ready"] = True

    @guard.callpoint("value")
    def value(ctx: Context) -> bool:
        return ctx["guard"]["ready"]

    @namespace("duplicate", requires=("guard",))
    def duplicate(ctx: Context) -> None:
        initialized.append("duplicate")

    @duplicate.hook("guard:value")
    def conflicting_value(ctx: Context) -> bool:
        return False

    cases = {
        "缺失 namespace 依赖": (guard.spec, ModuleSpec("missing", depends=("absent",))),
        "依赖环": (guard.spec, ModuleSpec("a", depends=("b",)), ModuleSpec("b", depends=("a",))),
        "single 同优先级冲突": (guard.spec, duplicate.spec),
    }
    for label, modules in cases.items():
        try:
            Host(modules).build()
        except ValueError as error:
            show(label, error)
        else:
            raise AssertionError(f"应在初始化之前拒绝：{label}")
    show("实际执行过的初始化函数", initialized)
    if initialized:
        raise AssertionError("无效装配不应产生初始化效果")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "scene", nargs="?", default="all", choices=("all", "hooks", "context", "lifecycle", "validation")
    )
    parser.add_argument("--amount", type=int, default=3, help="hooks 场景传给 increment 的增量，默认 3")
    parser.add_argument("--fail-run", action="store_true", help="在 lifecycle 场景触发并接收一次后台故障")
    args = parser.parse_args()
    console.print("Aurora Kernel Playground · 真实内核 / 内存状态 / 无需模型或个人配置")
    if args.scene in ("all", "hooks"):
        demo_hooks(args.amount)
    if args.scene in ("all", "context"):
        demo_context()
    if args.scene in ("all", "lifecycle"):
        asyncio.run(demo_lifecycle(fail_run=args.fail_run))
    if args.scene in ("all", "validation"):
        demo_validation()
    console.print("\n演示完成；修改 modules/kernel/fixtures.py 中的声明或本场景后可重新运行。")


if __name__ == "__main__":
    main()

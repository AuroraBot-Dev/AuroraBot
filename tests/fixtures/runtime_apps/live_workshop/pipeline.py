"""巡检工具内部的串行、循环、分支和并行装配。"""

import asyncio
from typing import cast

from aurora_agent.tools import ToolInstance
from aurora_control import Branch, ExecutionPlug, ExecutionSlot, Parallel, Serial, StateBinding, While
from aurora_core.hooks import HookConnections
from aurora_core.ids import Id

PIPELINE = Id("dev.example.workshop:state/pipeline")
INSPECT = Id("dev.example.workshop:handlers/inspect")
STEPS = ("initialize", "increment", "odd", "even", "double", "square")


async def declared(request):
    """组件定义的执行声明；实际执行由工具工厂绑定实例。"""
    raise RuntimeError("请使用工具工厂创建的执行实例")


async def create_inspector(*, registry, ctx, storage, instance_id, input_state, output_state, config):
    hooks = HookConnections(registry)
    counter = StateBinding(PIPELINE, (("part", "count"),))
    parity = StateBinding(PIPELINE, (("part", "parity"),))
    outputs = {name: StateBinding(PIPELINE, (("part", name),)) for name in ("double", "square")}

    def slot(component, name):
        return ExecutionSlot(component.definition_id, hooks, instance_id=f"{instance_id}/{name}")

    def plug(name, execute):
        return ExecutionPlug(Id(f"dev.example.workshop:handlers/{name}"), execute, instance_id=f"{instance_id}/{name}")

    def arguments(request):
        return input_state.get(ctx, request)["arguments"]

    def count(request):
        return cast(int, counter.get(ctx, request))

    async def initialize(request):
        counter.set(ctx, request, 0)
        if arguments(request)["fail"]:
            raise RuntimeError("示例巡检工具故障")

    async def increment(request):
        await asyncio.sleep(arguments(request)["delay"])
        counter.set(ctx, request, count(request) + 1)

    def marker(name):
        async def execute(request):
            parity.set(ctx, request, name)

        return execute

    def calculate(name):
        async def execute(request):
            await asyncio.sleep(arguments(request)["delay"])
            value = count(request)
            outputs[name].set(ctx, request, value * 2 if name == "double" else value * value)

        return execute

    try:
        root, body, branch_slot, loop_slot, parallel_slot = (
            slot(Serial, "root"),
            slot(Serial, "body"),
            slot(Branch, "parity"),
            slot(While, "loop"),
            slot(Parallel, "parallel"),
        )
        root.connect(plug("initialize", initialize))
        body.connect(plug("increment", increment))
        for name in ("odd", "even"):
            branch_slot.connect(plug(name, marker(name)))
        branch = Branch(
            ctx, branch_slot, lambda request: f"{instance_id}/{'even' if count(request) % 2 == 0 else 'odd'}"
        )
        body.connect(branch.plug)
        loop_slot.connect(Serial(ctx, body).plug)
        root.connect(
            While(
                ctx,
                loop_slot,
                lambda request: count(request) < arguments(request)["steps"],
                max_iterations=20,
            ).plug
        )
        for name in outputs:
            parallel_slot.connect(plug(name, calculate(name)))
        root.connect(Parallel(ctx, parallel_slot, concurrency=2).plug)
        pipeline = Serial(ctx, root)
    except BaseException:
        hooks.close()
        raise

    async def execute(request):
        try:
            await pipeline.execute(request)
            output_state.set(
                ctx,
                request,
                {
                    "count": counter.get(ctx, request),
                    "parity": parity.get(ctx, request),
                    **{name: binding.get(ctx, request) for name, binding in outputs.items()},
                },
            )
        finally:
            for address in ctx.list(key=PIPELINE):
                if dict(address.location).get("run_id") == request.run_id:
                    ctx.delete(address.key, location=dict(address.location))

    async def close():
        hooks.close()

    return ToolInstance(
        ExecutionPlug(INSPECT, execute, {"input": input_state, "output": output_state}, instance_id=instance_id), close
    )

"""通过 ctx 观察串行、条件循环、分支和并行组件；用于跨进程回归验收。"""

import argparse
import asyncio
import json
import math
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path
from uuid import uuid4

from aurora_control import (
    CONTROL_STATE,
    Branch,
    ExecutionLink,
    ExecutionPlug,
    ExecutionRequest,
    ExecutionSlot,
    Parallel,
    Serial,
    StateBinding,
    While,
    component_entries,
    plugin,
)
from aurora_core import Id
from aurora_core.bootstrap import bootstrap
from aurora_core.ctx import Context, StateChange, StateKey
from aurora_core.discovery import register_plugins
from aurora_core.hooks import HookConnections
from aurora_core.lifecycle import Lifecycle, LifecycleComponent, install_lifecycle_slots
from aurora_core.persistence import ContextPersistence
from aurora_core.registry import DefinitionRegistry, RegistryEntry
from aurora_core.storage import StorageService

VALUE = Id("dev.example.control:state/value")


def make_plug(
    registry: DefinitionRegistry,
    definition_id: Id,
    execute: Callable[[ExecutionRequest], Awaitable[None]],
    states: Mapping[str, StateBinding] | None = None,
    *,
    instance_id: str,
) -> ExecutionPlug:
    """由示例装配显式登记局部业务组件，再绑定具体执行实例。"""
    registry.register_many(component_entries(definition_id, execute, execute, provider="dev.example.control"))
    return ExecutionPlug(definition_id, execute, states or {}, instance_id=instance_id)


def state(instance_id: str) -> StateBinding:
    return StateBinding(VALUE, (("instance_id", instance_id),))


def number(ctx: Context, source: StateBinding, request: ExecutionRequest) -> int:
    value = source.get(ctx, request)
    assert isinstance(value, int)
    return value


def assemble(registry: DefinitionRegistry, ctx: Context, hooks: HookConnections, steps: int, delay: float) -> Serial:
    """装配交换地址；各执行函数只接收身份，自行读写 ctx，不返回业务结果。"""
    counter = state("counter")
    root_slot = ExecutionSlot(Serial.definition_id, hooks, instance_id="root")

    async def initialize(request: ExecutionRequest) -> None:
        counter.set(ctx, request, 0)

    async def increment(request: ExecutionRequest) -> None:
        await asyncio.sleep(delay)
        counter.set(ctx, request, number(ctx, counter, request) + 1)

    root_slot.connect(
        make_plug(registry, Id("dev.example.control:handlers/initialize"), initialize, instance_id="initialize")
    )
    body_slot = ExecutionSlot(Serial.definition_id, hooks, instance_id="body")
    counter_link = body_slot.connect(
        make_plug(
            registry, Id("dev.example.control:handlers/counter"), increment, {"value": counter}, instance_id="counter"
        )
    )

    # 插槽从生产方握手结果取得地址，再向消费方提供同一位置。
    branch_slot = ExecutionSlot(
        Branch.definition_id, hooks, instance_id="parity", states={"input": counter_link.plug.states["value"]}
    )

    def connect_marker(name: str, label: str) -> None:
        output = state(name)

        async def execute(request: ExecutionRequest) -> None:
            value = number(ctx, link.slot_states["input"], request)
            output.set(ctx, request, {"number": value, "label": label})

        link = branch_slot.connect(
            make_plug(
                registry, Id(f"dev.example.control:handlers/{name}"), execute, {"output": output}, instance_id=name
            )
        )

    connect_marker("odd", "奇数分支")
    connect_marker("even", "偶数分支")
    branch = Branch(ctx, branch_slot, lambda request: "even" if number(ctx, counter, request) % 2 == 0 else "odd")
    body_slot.connect(branch.plug)

    loop_slot = ExecutionSlot(While.definition_id, hooks, instance_id="loop")
    loop_slot.connect(Serial(ctx, body_slot).plug)
    loop = While(ctx, loop_slot, lambda request: number(ctx, counter, request) < steps, max_iterations=steps)
    root_slot.connect(loop.plug)

    parallel_slot = ExecutionSlot(
        Parallel.definition_id, hooks, instance_id="parallel", states={"input": counter_link.plug.states["value"]}
    )

    def connect_calculation(name: str, calculate: Callable[[int], int], wait: float) -> ExecutionLink:
        output = state(name)

        async def execute(request: ExecutionRequest) -> None:
            output.set(ctx, request, {"status": "running"})
            try:
                await asyncio.sleep(wait)
                value = calculate(number(ctx, link.slot_states["input"], request))
                output.set(ctx, request, {"status": "completed", "value": value})
            except asyncio.CancelledError:
                output.set(ctx, request, {"status": "cancelled"})
                raise

        link = parallel_slot.connect(
            make_plug(
                registry, Id(f"dev.example.control:handlers/{name}"), execute, {"output": output}, instance_id=name
            )
        )
        return link

    calculations = (
        connect_calculation("double", lambda value: value * 2, delay * 2),
        connect_calculation("square", lambda value: value * value, delay),
    )
    root_slot.connect(Parallel(ctx, parallel_slot, concurrency=2).plug)

    async def summarize(request: ExecutionRequest) -> None:
        result = {"count": number(ctx, counter, request)}
        for link in calculations:
            output = link.plug.states["output"].get(ctx, request)
            assert isinstance(output, dict)
            result[link.plug.instance_id] = output["value"]
        state("summary").set(ctx, request, result)

    root_slot.connect(
        make_plug(
            registry,
            Id("dev.example.control:handlers/summary"),
            summarize,
            {"output": state("summary")},
            instance_id="summary",
        )
    )
    return Serial(ctx, root_slot)


def observe(change: StateChange) -> None:
    """观察真实 ctx 通知；控制组件只显示状态转移，业务组件显示写入值。"""
    if change.action != "set":
        return
    instance = dict(change.address.location)["instance_id"]
    if change.address.key == CONTROL_STATE:
        value = change.value
        assert isinstance(value, dict)
        previous = change.previous if isinstance(change.previous, dict) else {}
        if previous.get("status") != value["status"]:
            print(f"[控制] {instance}: {value['status']}", flush=True)
    else:
        print(f"[状态] {instance}: {json.dumps(change.value, ensure_ascii=False)}", flush=True)


async def run(data_dir: Path, steps: int, delay: float) -> None:
    registry = bootstrap()
    register_plugins(registry, (plugin(),))
    registry.register(RegistryEntry(VALUE, "state_key", StateKey(), "control_flow"))
    install_lifecycle_slots(registry)
    ctx = Context(registry)
    hooks = HookConnections(registry)
    root = assemble(registry, ctx, hooks, steps, delay)
    storage = StorageService(data_dir)
    host = Lifecycle(
        ctx,
        hooks,
        [LifecycleComponent("root")],
        persistence=ContextPersistence(ctx, storage.snapshot_store()),
        storage=storage,
    )
    request = ExecutionRequest(uuid4().hex)

    def configure() -> None:
        # 此示例独占宿主；恢复时没有在途调用，控制状态无需恢复执行。
        for address in ctx.list(key=CONTROL_STATE):
            ctx.delete(address.key, location=dict(address.location))

    await host.start(configure=configure)
    subscription = ctx.subscribe(observe)
    outcome: dict[str, object] = {"status": "failed"}
    try:
        print(f"运行 ID: {request.run_id}", flush=True)
        await host.run(root.execute, request)
        result = state("summary").get(ctx, request)
        outcome = {"status": "completed", "result": result}
        print(f"结果: {json.dumps(result, ensure_ascii=False)}", flush=True)
    except asyncio.CancelledError:
        outcome = {"status": "cancelled"}
        raise
    finally:
        ctx.unsubscribe(subscription)
        try:
            # 示例只保留最近一次运行的结果；业务插件自行决定自己的保留策略。
            latest = state("run")
            latest.set(ctx, request, outcome)
            for address in ctx.list(key=VALUE):
                if address != latest.address(request):
                    ctx.delete(address.key, location=dict(address.location))
        finally:
            await host.stop()
    print(f"快照: {data_dir / 'framework' / 'ctx.json'}")


def main() -> None:
    parser = argparse.ArgumentParser(description="观察四类控制组件通过 ctx 协作，无需网络或模型密钥")
    parser.add_argument("--data-dir", type=Path, required=True, help="此示例独占的持久化数据目录")
    parser.add_argument("--steps", type=int, default=3, help="循环次数，默认为 3")
    parser.add_argument("--delay", type=float, default=0.2, help="每步等待秒数，默认为 0.2")
    args = parser.parse_args()
    if args.steps < 1:
        parser.error("--steps 必须为正整数")
    if not math.isfinite(args.delay) or args.delay < 0:
        parser.error("--delay 必须为非负有限数")
    try:
        asyncio.run(run(args.data_dir, args.steps, args.delay))
    except KeyboardInterrupt:
        print("已取消。")
        raise SystemExit(130) from None


if __name__ == "__main__":
    main()

"""独立 Agent 示例：运行调度、本地工具、运行中引导和跨激活上下文。"""

import argparse
import asyncio
import json
import math
from pathlib import Path
from typing import cast

from aurora_adapter.model import ChatRequest
from aurora_adapter.model.testing import FakeModel, FakeReply
from aurora_agent.model import ModelCall
from aurora_agent.model import plugin as model_plugin
from aurora_agent.react import ReActAgent
from aurora_agent.react import plugin as react_plugin
from aurora_agent.react_defaults import ReActContext, ReActDefaults
from aurora_agent.react_defaults import plugin as defaults_plugin
from aurora_agent.runtime import AgentRuntime
from aurora_agent.tools import TOOLS, ToolExecutor, ToolSpec
from aurora_agent.tools import plugin as tools_plugin
from aurora_control import ExecutionPlug, ExecutionRequest, InstanceStateBinding, StateBinding, component_entries
from aurora_core import Id, entry_from, hook_handler
from aurora_core.bootstrap import bootstrap
from aurora_core.ctx import Context, StateChange, StateKey
from aurora_core.discovery import register_plugins
from aurora_core.hooks import HookConnections
from aurora_core.lifecycle import CLEAN, STOP, Lifecycle, LifecycleComponent, install_lifecycle_slots
from aurora_core.persistence import ContextPersistence
from aurora_core.registry import RegistryEntry
from aurora_core.storage import StorageService

STATE = Id("dev.example.react:state/data")
ADD = Id("dev.example.react:handlers/add")


def observe(change: StateChange) -> None:
    """终端展示内部推理增量和工具开始事件；不承担消息发送工具的职责。"""
    if change.action != "set" or not isinstance(change.value, dict):
        return
    value = change.value
    if "text" in value:
        previous = change.previous if isinstance(change.previous, dict) else {}
        print(value["text"][len(previous.get("text", "")) :], end="", flush=True)
        if value["status"] != "running":
            print(f"\n模型状态: {value['status']}", flush=True)
    elif "call" in value and value["result"] is None:
        print(f"工具开始: {value['call']['name']}", flush=True)


async def run(args: argparse.Namespace) -> None:
    registry = bootstrap()
    register_plugins(registry, (react_plugin(), model_plugin(), tools_plugin(), defaults_plugin()))
    install_lifecycle_slots(registry)
    registry.register(RegistryEntry(STATE, "state_key", StateKey(), "react_example"))
    ctx, hooks = Context(registry), HookConnections(registry)
    request = ExecutionRequest("maintenance")

    def fixed(name):
        return InstanceStateBinding(STATE, (("instance_id", "agent"), ("name", name)))

    def transient(name):
        return StateBinding(STATE, (("instance_id", "agent"), ("name", name)))

    agent = ReActAgent(
        ctx,
        hooks,
        instance_id="agent",
        inbox=fixed("inbox"),
        progress=fixed("progress"),
        runtime=fixed("runtime"),
        batch=transient("batch"),
        decision=transient("decision"),
        max_iterations=5,
    )

    def respond(model_request: ChatRequest) -> FakeReply:
        if args.text == "无需行动":
            return FakeReply()
        if len(client.requests) == 1:
            return FakeReply(
                ("准备调用工具",),
                tool_calls=(
                    {
                        "id": f"add-{request.run_id}",
                        "name": "add",
                        "arguments": {"a": args.a, "b": args.b},
                    },
                ),
            )
        tool_message = next(message for message in reversed(model_request["messages"]) if message["role"] == "tool")
        assert isinstance(tool_message["content"], str)
        result = json.loads(tool_message["content"])
        return (
            FakeReply(("计算结果：", str(result["value"])))
            if result["status"] == "completed"
            else FakeReply(("工具反馈：", result["error"]["code"]))
        )

    client = FakeModel(respond, delay=0.01)
    model = ModelCall(
        ctx, client, instance_id="model", request_state=transient("model_input"), output_state=transient("model_output")
    )
    tools = ToolExecutor(
        ctx,
        registry,
        hooks,
        instance_id="tools",
        request_state=transient("tool_calls"),
        output_state=transient("tool_results"),
        current_state=transient("tool_current"),
        timeout=args.timeout,
    )
    tool_input, tool_output = transient("add_input"), transient("add_output")

    async def add(execution: ExecutionRequest) -> None:
        value = tool_input.get(ctx, execution)
        assert isinstance(value, dict)
        await asyncio.sleep(args.tool_delay)
        if args.tool_error:
            raise ValueError("模拟本地工具失败")
        tool_output.set(ctx, execution, value["arguments"]["a"] + value["arguments"]["b"])

    registry.register_many(component_entries(ADD, add, add, provider="react_example"))
    tool_id = Id("dev.example.react:tools/add")
    registry.register(
        RegistryEntry(
            tool_id,
            "tool",
            ToolSpec(
                ADD,
                {
                    "name": "add",
                    "description": "两个整数相加",
                    "parameters": {
                        "type": "object",
                        "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}},
                        "required": ["a", "b"],
                        "additionalProperties": False,
                    },
                },
            ),
            "react_example",
            register_to=TOOLS,
        )
    )
    tools.connect(tool_id, ExecutionPlug(ADD, add, {"input": tool_input, "output": tool_output}, instance_id="add"))
    defaults = ReActDefaults(
        agent, model, tools, context_state=fixed("context"), system_prompt="根据环境自主选择行动；无需行动时可以结束。"
    )
    defaults.connect()

    executing = False

    async def execute(execution: ExecutionRequest) -> None:
        nonlocal executing
        executing = True
        try:
            await agent.execute(execution)
        finally:
            executing = False

    runtime = AgentRuntime(get_agent=lambda: agent, execute=execute, is_executing=lambda: executing)

    @hook_handler("dev.example.react:handlers/stop_agent", slot=STOP)
    async def stop_agent() -> None:
        await runtime.close()

    @hook_handler("dev.example.react:handlers/close", slot=CLEAN)
    async def close() -> None:
        await client.aclose()
        keep = {model.output_state.address(request)}
        try:
            context = cast(ReActContext, defaults.context_state.get(ctx, request))
        except KeyError:
            context = {"messages": [], "guidance_sequence": 0, "pending": None}
        if context["pending"] is not None:
            keep.add(tools.output_state.address(ExecutionRequest(context["pending"]["run_id"])))
        for address in ctx.list(key=STATE):
            if "run_id" in dict(address.location) and address not in keep:
                ctx.delete(address.key, location=dict(address.location))
        agent.inbox.set(ctx, request, agent.pending(request))

    for owner, phase, handler in (("agent", STOP, stop_agent), ("model", CLEAN, close)):
        entry = entry_from(handler, provider="react_example")
        registry.register(entry)
        hooks.connect(phase, entry.id, slot_instance=owner, handler_instance=owner)
    storage = StorageService(args.data_dir)
    host = Lifecycle(
        ctx,
        hooks,
        [
            LifecycleComponent("model"),
            LifecycleComponent("agent", depends_on=("model",), stop_accepting=runtime.stop_accepting),
        ],
        persistence=ContextPersistence(ctx, storage.snapshot_store()),
        storage=storage,
    )
    await host.start()
    subscriptions = []
    try:
        runtime.start()
        guided = False

        def guide(change: StateChange) -> None:
            nonlocal guided
            if (
                args.guide
                and not guided
                and change.action == "set"
                and isinstance(change.value, dict)
                and change.value.get("text") == "准备调用工具"
            ):
                guided = True
                runtime.submit(args.guide)
                print("\n已接纳新的引导通知。", flush=True)

        subscriptions.extend((ctx.subscribe(observe, key=STATE), ctx.subscribe(guide, key=STATE)))
        receipt = runtime.submit(args.text)
        request = ExecutionRequest(receipt.run.run_id)
        print(f"运行 ID: {request.run_id}", flush=True)
        result = await receipt.run.wait()
        if result.status != "completed":
            raise RuntimeError(f"激活未完成：{result.status}，{result.error}")
        print("激活状态: completed", flush=True)
    finally:
        for subscription in subscriptions:
            ctx.unsubscribe(subscription)
        await host.stop()
    print(f"快照: {args.data_dir / 'framework' / 'ctx.json'}")


def main() -> None:
    parser = argparse.ArgumentParser(description="离线 ReAct：工具往返、失败观察、引导与状态恢复，无需网络和密钥")
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--text", default="计算两数之和", help="使用“无需行动”演示空输出结束")
    parser.add_argument("--a", type=int, default=2)
    parser.add_argument("--b", type=int, default=3)
    parser.add_argument("--guide", help="在模型流式输出期间追加的引导")
    parser.add_argument("--tool-error", action="store_true")
    parser.add_argument("--tool-delay", type=float, default=0)
    parser.add_argument("--timeout", type=float, default=2)
    args = parser.parse_args()
    if (
        not math.isfinite(args.tool_delay)
        or args.tool_delay < 0
        or not math.isfinite(args.timeout)
        or args.timeout <= 0
    ):
        parser.error("tool-delay 必须为非负有限数，timeout 必须为正有限数")
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        print("已取消，待接纳的工具结果保留到下次激活。")
        raise SystemExit(130) from None


if __name__ == "__main__":
    main()

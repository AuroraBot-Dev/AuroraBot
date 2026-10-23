"""独立 Agent 的离线场景：uv run python -m playground.examples.agent。"""

from __future__ import annotations

import argparse
import asyncio
from typing import TYPE_CHECKING

from rich.console import Console

from aurora_agent import Agent, RunRequest
from playground.modules.agent.fixtures import DemoModel, EchoTool, Gate, ReconsiderPolicy

if TYPE_CHECKING:
    from aurora_agent import Run, ToolPolicy

console = Console(highlight=False, markup=False)
SCENARIOS = ("loop", "append", "append-model", "cancel", "policy", "unknown")


def create_run(
    scenario: str,
    message: str,
    model: DemoModel,
    tool: EchoTool,
    *,
    policy: ToolPolicy | None = None,
) -> Run:
    agent = Agent(
        instructions="依据输入调用工具，再用中文回答。",
        model="demo/local",
        provider=model,
        tools=(tool,),
        policy=policy,
    )
    return agent.create(RunRequest(message, run_id=f"demo-{scenario}"))


def show_snapshot(run: Run, label: str) -> None:
    snapshot = run.snapshot()
    console.print(f"\n{label}：{snapshot.status.value}")
    console.print("  历史：" + " → ".join(message.role for message in snapshot.messages))
    console.print(f"  排队输入：{[message.content for message in snapshot.queued_messages]}")
    console.print(f"  工具状态：{[(record.call.call_id, record.status.value) for record in snapshot.calls]}")
    console.print(f"  调用计数：模型={snapshot.stats.model_calls}，工具={snapshot.stats.tool_calls}")
    if snapshot.result is not None:
        console.print(f"  结果：{snapshot.result.output or snapshot.result.reason}")


async def show_events(run: Run) -> None:
    console.print("\n事件记录：")
    async for event in run.events():
        call = f" · {event.call_id}" if event.call_id is not None else ""
        console.print(f"  {event.sequence:02d} · {event.kind.value} · {event.status.value}{call}")


async def tool_boundary(scenario: str, message: str, extra: str) -> Run:
    gate = Gate()
    tool = EchoTool(gate=gate, trace=console.print)
    run = create_run(scenario, message, DemoModel(trace=console.print), tool)
    await run.step()
    show_snapshot(run, "模型已提出两个调用")
    async with asyncio.TaskGroup() as tasks:
        driving = tasks.create_task(run.step())
        await gate.entered.wait()
        if scenario == "cancel":
            run.cancel()
            console.print("\n宿主请求取消，等待正在执行的工具返回。")
        else:
            run.append_message(extra)
            console.print("\n宿主在工具执行期间追加输入。")
        show_snapshot(run, "工具尚未返回")
        gate.release.set()
    driving.result()
    show_snapshot(run, "第一个工具返回后")
    if scenario == "append":
        await run.step()
        show_snapshot(run, "两个调用全部配对，输入等待下一轮交付")
    await run.run()
    console.print(f"\n实际执行的工具调用：{tool.executed}")
    return run


async def model_boundary(message: str, extra: str) -> Run:
    gate = Gate()
    model = DemoModel(gate=gate, answer_only=True, trace=console.print)
    run = create_run("append-model", message, model, EchoTool(trace=console.print))
    async with asyncio.TaskGroup() as tasks:
        driving = tasks.create_task(run.run())
        await gate.entered.wait()
        run.append_message(extra)
        show_snapshot(run, "模型正在生成本轮回答，宿主已追加输入")
        gate.release.set()
    driving.result()
    console.print("\n第一轮回答保留在历史中，新增输入由第二轮处理。")
    return run


async def run_scenario(scenario: str, message: str, extra: str) -> None:
    console.rule(f"独立 Agent · {scenario}")
    if scenario in {"append", "cancel"}:
        run = await tool_boundary(scenario, message, extra)
    elif scenario == "append-model":
        run = await model_boundary(message, extra)
    else:
        tool = EchoTool(unknown=scenario == "unknown", trace=console.print)
        policy = ReconsiderPolicy(trace=console.print) if scenario == "policy" else None
        run = create_run(scenario, message, DemoModel(trace=console.print), tool, policy=policy)
        show_snapshot(run, "创建后")
        await run.run()
        if scenario == "unknown":
            await run.run()
            console.print(f"\n再次推进终态，实际工具调用仍为：{tool.executed}")
        elif scenario == "policy":
            console.print(f"\n策略阻止了原提案，实际工具调用：{tool.executed}")
    show_snapshot(run, "最终状态")
    await show_events(run)


async def main_async(scenario: str, message: str, extra: str) -> None:
    for selected in SCENARIOS if scenario == "all" else (scenario,):
        await run_scenario(selected, message, extra)


def main() -> None:
    parser = argparse.ArgumentParser(description="独立 aurora_agent 的离线 ReAct 与宿主控制演示")
    parser.add_argument("scenario", nargs="?", choices=("all", *SCENARIOS), default="all", help="场景，默认全部")
    parser.add_argument("--message", default="收集两项事实并汇总。", help="初始任务")
    parser.add_argument("--extra", default="补充条件：请用一句话回答。", help="追加消息场景中的输入")
    args = parser.parse_args()
    if not args.message.strip() or not args.extra.strip():
        parser.error("初始任务和追加输入不能为空")
    asyncio.run(main_async(args.scenario, args.message, args.extra))


if __name__ == "__main__":
    main()

"""Agent 只声明离线装配、业务操作和观察投影；实例管理与记录由公共工作台提供。"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from aurora_agent import RunLimits, RunRequest
from playground.modules.agent.case import ScriptedModel, ScriptedPolicy, ScriptedTool
from playground.modules.agent.fixtures import DemoModel, EchoTool, ReconsiderPolicy
from playground.modules.agent.models import Append, Create, State
from playground.modules.agent.records import Inspection
from playground.modules.agent.workbench import Workbench
from playground.protocol import Empty, Model, Module, Operation
from playground.workspace import WorkspaceSpec

if TYPE_CHECKING:
    from collections.abc import Iterator

EXAMPLE = {
    "case": {
        "message": "查询温度后汇总。",
        "replies": [
            {"tool_calls": [{"call_id": "read-1", "name": "temperature", "arguments": {}}]},
            {"content": "温度为 23 度。"},
        ],
        "tools": [{"name": "temperature", "outcomes": [{"content": "23"}]}],
    }
}


@dataclass(frozen=True, slots=True)
class Environment:
    configuration: Create
    bench: Workbench


def assemble(configuration: Create, run_id: str) -> Workbench:
    case = configuration.case
    if case is not None:
        return Workbench(
            RunRequest(case.message, run_id=run_id),
            instructions=case.instructions,
            model=case.model,
            provider=ScriptedModel(case.replies),
            tools=[ScriptedTool(tool) for tool in case.tools],
            policy=ScriptedPolicy(case.decisions) if case.decisions else None,
            limits=case.limits(),
        )
    return Workbench(
        RunRequest(configuration.message, run_id=run_id),
        instructions="依据输入调用工具，再用中文回答。",
        model="demo/local",
        provider=DemoModel(answer_only=configuration.scenario == "answer"),
        tools=(EchoTool(unknown=configuration.scenario == "unknown"),),
        policy=ReconsiderPolicy() if configuration.scenario == "policy" else None,
        limits=RunLimits(configuration.max_model_calls, configuration.max_tool_calls, configuration.max_context_chars),
    )


@contextmanager
def open_instance(configuration: Model, instance_id: str) -> Iterator[Environment]:
    parsed = Create.model_validate(configuration)
    yield Environment(parsed, assemble(parsed, instance_id))


def snapshot(environment: Environment) -> State:
    return State.of(environment.bench.run.snapshot())


async def step(environment: Environment) -> State:
    return State.of(await environment.bench.run.step())


async def run(environment: Environment) -> State:
    await environment.bench.run.run()
    return snapshot(environment)


def append(environment: Environment, *, message: str) -> State:
    environment.bench.run.append_message(message)
    return snapshot(environment)


def cancel(environment: Environment) -> State:
    environment.bench.run.cancel()
    return snapshot(environment)


def inspect(environment: Environment) -> Inspection:
    return Inspection.of(environment.bench, environment.configuration)


def project(value: Model) -> dict[str, Any]:
    # 新身份下复现只忽略宿主分配的运行身份；不改写消息正文或工具参数中的同名字段。
    if isinstance(value, State):
        return value.model_dump(mode="json", exclude={"run_id"})
    if isinstance(value, Inspection):
        return value.model_dump(mode="json", exclude={"state": {"run_id"}})
    return value.model_dump(mode="json")


SPEC = WorkspaceSpec(
    configuration=Create,
    open=open_instance,
    snapshot=Operation(
        "snapshot", "读取消息、排队输入、工具回执和运行状态。", Empty, State, snapshot, {}, record=False
    ),
    operations=(
        Operation("step", "推进一次模型调用或工具调用。", Empty, State, step, {}, replayable=True),
        Operation(
            "append", "在安全边界交付追加输入。", Append, State, append, {"message": "补充条件"}, replayable=True
        ),
        Operation("run", "连续执行至终态；不重放已完成的效果。", Empty, State, run, {}, replayable=True),
        Operation("cancel", "协作式取消，不撤销已经发生的效果。", Empty, State, cancel, {}, replayable=True),
        Operation(
            "inspect", "显式查看实际模型请求、响应和无正文的端口轨迹。", Empty, Inspection, inspect, {}, record=False
        ),
    ),
    isolated=True,
    project=project,
    identity="run_id",
    default_id="demo",
    example=EXAMPLE,
)

MODULE = Module("agent", "独立 Agent：可编辑离线依赖、逐步执行、端口观察与记录复现。", workspace=SPEC)

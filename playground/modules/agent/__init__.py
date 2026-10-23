"""Agent 工作台的 JSON 适配；装配、观察与离线记录均留在本模块内。"""

from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass, field
from typing import Any

from aurora_agent import RunLimits, RunRequest
from playground.modules.agent.case import ScriptedModel, ScriptedPolicy, ScriptedTool
from playground.modules.agent.fixtures import DemoModel, EchoTool, ReconsiderPolicy
from playground.modules.agent.models import Append, Create, State, Target
from playground.modules.agent.records import (
    Archive,
    Checkpoint,
    Control,
    Inspection,
    Replay,
    ReplayResult,
)
from playground.modules.agent.workbench import Workbench
from playground.protocol import Module, Operation

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


def assemble(configuration: Create) -> Workbench:
    """每次重新构造依赖，避免场景的游标和工具状态泄漏到其他运行。"""
    case = configuration.case
    if case is not None:
        return Workbench(
            RunRequest(case.message, run_id=configuration.run_id),
            instructions=case.instructions,
            model=case.model,
            provider=ScriptedModel(case.replies),
            tools=[ScriptedTool(tool) for tool in case.tools],
            policy=ScriptedPolicy(case.decisions) if case.decisions else None,
            limits=case.limits(),
        )
    return Workbench(
        RunRequest(configuration.message, run_id=configuration.run_id),
        instructions="依据输入调用工具，再用中文回答。",
        model="demo/local",
        provider=DemoModel(answer_only=configuration.scenario == "answer"),
        tools=(EchoTool(unknown=configuration.scenario == "unknown"),),
        policy=ReconsiderPolicy() if configuration.scenario == "policy" else None,
        limits=RunLimits(configuration.max_model_calls, configuration.max_tool_calls, configuration.max_context_chars),
    )


@dataclass(slots=True)
class Experiment:
    configuration: Create
    bench: Workbench
    initial: State
    checkpoints: list[Checkpoint] = field(default_factory=list)

    async def apply(self, control: Control) -> State:
        run = self.bench.run
        error_type = None
        try:
            if control.action == "step":
                await run.step()
            elif control.action == "run":
                await run.run()
            elif control.action == "append":
                assert control.message is not None
                run.append_message(control.message)
            else:
                run.cancel()
        except Exception as error:
            error_type = type(error).__name__
            # UI 边界将任意端口异常转成可交付的失败；原始类型保留在检查点中，
            # 不把异常正文（可能包含请求或凭据）复制到响应。
            raise RuntimeError(f"Agent 操作失败：{error_type}；使用 inspect 查看保留的状态。") from error
        except BaseException as error:
            error_type = type(error).__name__
            raise
        finally:
            state = State.of(run.snapshot())
            self.checkpoints.append(Checkpoint(control=control, state=state, error_type=error_type))
        return state

    def export(self) -> Archive:
        inspection = Inspection.of(self.bench, self.configuration)
        return Archive(
            configuration=self.configuration.model_copy(deep=True),
            initial=self.initial.model_copy(deep=True),
            checkpoints=[item.model_copy(deep=True) for item in self.checkpoints],
            trace=inspection.trace,
        )


class AgentSession:
    def __init__(self) -> None:
        self._experiments: dict[str, Experiment] = {}

    def get(self, run_id: str) -> Experiment:
        if run_id not in self._experiments:
            raise ValueError(f"运行不存在，请先 create：{run_id}")
        return self._experiments[run_id]

    def install(self, configuration: Create) -> State:
        if configuration.run_id in self._experiments:
            raise ValueError(f"运行身份已存在，请使用新的 run_id：{configuration.run_id}")
        bench = assemble(configuration)
        initial = State.of(bench.run.snapshot())
        self._experiments[configuration.run_id] = Experiment(configuration.model_copy(deep=True), bench, initial)
        return initial

    async def create(self, **configuration: Any) -> State:
        return self.install(Create.model_validate(configuration))

    async def step(self, *, run_id: str = "demo") -> State:
        return await self.get(run_id).apply(Control(action="step"))

    async def append(self, *, message: str, run_id: str = "demo") -> State:
        return await self.get(run_id).apply(Control(action="append", message=message))

    async def run(self, *, run_id: str = "demo") -> State:
        return await self.get(run_id).apply(Control(action="run"))

    async def snapshot(self, *, run_id: str = "demo") -> State:
        return State.of(self.get(run_id).bench.run.snapshot())

    async def cancel(self, *, run_id: str = "demo") -> State:
        return await self.get(run_id).apply(Control(action="cancel"))

    async def inspect(self, *, run_id: str = "demo") -> Inspection:
        experiment = self.get(run_id)
        return Inspection.of(experiment.bench, experiment.configuration)

    async def reset(self, *, run_id: str = "demo") -> State:
        configuration = self.get(run_id).configuration
        # 先装配成功再替换，不丢弃一个仍可检查的运行。
        bench = assemble(configuration)
        initial = State.of(bench.run.snapshot())
        self._experiments[run_id] = Experiment(configuration, bench, initial)
        return initial

    async def export(self, *, run_id: str = "demo") -> Archive:
        return self.get(run_id).export()

    async def replay(self, *, archive: dict[str, Any], run_id: str = "replay") -> ReplayResult:
        record = Archive.model_validate(archive)
        configuration = record.configuration.model_copy(update={"run_id": run_id}, deep=True)
        initial = self.install(configuration)
        experiment = self.get(run_id)
        differences = []
        if initial.model_copy(update={"run_id": record.initial.run_id}) != record.initial:
            differences.append("initial")
        for index, checkpoint in enumerate(record.checkpoints):
            # 记录中显式包含的失败同样是待比对结果，不自动重试。
            with suppress(ValueError, TypeError, LookupError, RuntimeError):
                await experiment.apply(checkpoint.control)
            actual = experiment.checkpoints[-1]
            state = actual.state.model_copy(update={"run_id": checkpoint.state.run_id})
            if state != checkpoint.state or actual.error_type != checkpoint.error_type:
                differences.append(f"checkpoints[{index}]")
        actual_record = experiment.export()
        if actual_record.trace != record.trace:
            differences.append("trace")
        return ReplayResult(
            matched=not differences, differences=differences, state=State.of(experiment.bench.run.snapshot())
        )

    def operations(self) -> tuple[Operation, ...]:
        return (
            Operation("create", "创建独立运行：自定义 case 或使用预设场景。", Create, State, self.create, EXAMPLE),
            Operation("step", "推进一次模型调用或一个工具调用。", Target, State, self.step, {}),
            Operation("append", "排队追加输入，在安全边界交付。", Append, State, self.append, {"message": "补充条件"}),
            Operation("snapshot", "读取运行状态、消息、排队输入和工具回执。", Target, State, self.snapshot, {}),
            Operation("run", "连续执行至终态；不重放已完成的效果。", Target, State, self.run, {}),
            Operation("cancel", "协作式取消；已经发生的效果不会撤销。", Target, State, self.cancel, {}),
            Operation("inspect", "显式查看模型请求、响应和无正文的端口轨迹。", Target, Inspection, self.inspect, {}),
            Operation("reset", "重新装配当前离线配置；清空状态和依赖游标。", Target, State, self.reset, {}),
            Operation(
                "export", "显式导出离线配置与检查点；包含正文，请勿提交真实会话。", Target, Archive, self.export, {}
            ),
            Operation(
                "replay",
                "在新身份下离线重跑记录，逐检查点比对；不调用真实工具。",
                Replay,
                ReplayResult,
                self.replay,
                {
                    "archive": {
                        "configuration": {"case": {"message": "问候", "replies": [{"content": "你好"}]}},
                        "initial": {
                            "run_id": "demo",
                            "status": "ready",
                            "messages": [
                                {
                                    "role": "message",
                                    "content": "问候",
                                    "tool_calls": [],
                                    "tool_call_id": None,
                                    "is_error": False,
                                }
                            ],
                            "queued_messages": [],
                            "calls": [],
                            "stats": {"model_calls": 0, "tool_calls": 0, "input_tokens": None, "output_tokens": None},
                            "cancel_requested": False,
                            "result": None,
                        },
                        "checkpoints": [],
                        "trace": [],
                    }
                },
            ),
        )


def create() -> tuple[Operation, ...]:
    return AgentSession().operations()


MODULE = Module("agent", "独立 Agent 工作台：可编辑离线依赖、逐步执行、端口观察与记录复现。", create)

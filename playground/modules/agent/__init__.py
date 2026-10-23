"""独立 Agent 黑盒：状态属于会话，异步操作由会话的同一个事件循环驱动。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from aurora_agent import Agent, RunLimits, RunRequest
from playground.modules.agent.fixtures import DemoModel, EchoTool, ReconsiderPolicy
from playground.modules.agent.models import Append, Create, State, Target
from playground.protocol import Module, Operation

if TYPE_CHECKING:
    from aurora_agent import Run


class AgentSession:
    def __init__(self) -> None:
        self._runs: dict[str, Run] = {}

    def get(self, run_id: str) -> Run:
        if run_id not in self._runs:
            raise ValueError(f"运行不存在，请先 create：{run_id}")
        return self._runs[run_id]

    async def create(
        self,
        *,
        run_id: str = "demo",
        message: str = "收集两项事实并汇总。",
        scenario: str = "loop",
        max_model_calls: int = 32,
        max_tool_calls: int = 128,
    ) -> State:
        if run_id in self._runs:
            raise ValueError(f"运行身份已存在，请使用新的 run_id：{run_id}")
        agent = Agent(
            instructions="依据输入调用工具，再用中文回答。",
            model="demo/local",
            provider=DemoModel(answer_only=scenario == "answer"),
            tools=(EchoTool(unknown=scenario == "unknown"),),
            policy=ReconsiderPolicy() if scenario == "policy" else None,
            limits=RunLimits(max_model_calls=max_model_calls, max_tool_calls=max_tool_calls),
        )
        run = agent.create(RunRequest(message, run_id=run_id))
        self._runs[run_id] = run
        return State.of(run.snapshot())

    async def step(self, *, run_id: str = "demo") -> State:
        return State.of(await self.get(run_id).step())

    async def append(self, *, message: str, run_id: str = "demo") -> State:
        run = self.get(run_id)
        run.append_message(message)
        return State.of(run.snapshot())

    async def run(self, *, run_id: str = "demo") -> State:
        run = self.get(run_id)
        await run.run()
        return State.of(run.snapshot())

    async def snapshot(self, *, run_id: str = "demo") -> State:
        return State.of(self.get(run_id).snapshot())

    async def cancel(self, *, run_id: str = "demo") -> State:
        run = self.get(run_id)
        run.cancel()
        return State.of(run.snapshot())

    def operations(self) -> tuple[Operation, ...]:
        return (
            Operation("create", "创建独立 Run；同一会话内 run_id 不可重复。", Create, State, self.create, {}),
            Operation("step", "推进一次模型调用或一个工具调用。", Target, State, self.step, {}),
            Operation(
                "append",
                "排队追加普通输入，工具调用全部配对后交付。",
                Append,
                State,
                self.append,
                {"message": "请用一句话回答。"},
            ),
            Operation("snapshot", "读取状态、消息、排队输入和工具调用。", Target, State, self.snapshot, {}),
            Operation("run", "连续执行至终态；返回状态快照及最终结果。", Target, State, self.run, {}),
            Operation("cancel", "在步骤边界取消；已经发生的效果不会撤销。", Target, State, self.cancel, {}),
        )


def create() -> tuple[Operation, ...]:
    return AgentSession().operations()


MODULE = Module("agent", "独立 aurora_agent 与本地 Model/Tool；按 run_id 保留状态，支持逐步执行与追加输入。", create)

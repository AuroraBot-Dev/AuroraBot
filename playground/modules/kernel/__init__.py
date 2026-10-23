"""内核黑盒：复用示例声明，每个交互会话拥有独立 Host。"""

from __future__ import annotations

from typing import Any

from pydantic import Field

from aurora_kernel import Host
from playground.modules.kernel.fixtures import client, counter
from playground.modules.kernel.fixtures import extension as counter_extension
from playground.protocol import Empty, Model, Module, Operation


class Amount(Model):
    amount: int = Field(default=1, description="本次增量；启用 extension 时由高优先级实现乘以 2")


class Value(Model):
    value: int


class Reset(Model):
    extension: bool = Field(default=True, description="是否装配 extension 和依赖它的 client")


class State(Model):
    revision: int
    namespaces: dict[str, dict[str, Any]]


class Descriptions(Model):
    descriptions: list[str]


class Notification(Model):
    notified: bool


class KernelSession:
    def __init__(self) -> None:
        self._host: Host | None = None

    @property
    def host(self) -> Host:
        # 查询操作说明和校验输入时不构造宿主。
        if self._host is None:
            self._host = Host((counter, counter_extension, client)).build()
        return self._host

    def state(self) -> State:
        return State(revision=self.host.ctx.revision, namespaces=self.host.ctx.snapshot())

    def reset(self, *, extension: bool = True) -> State:
        self._host = Host((counter, counter_extension, client) if extension else (counter,)).build()
        return self.state()

    def increment(self, *, amount: int = 1) -> Value:
        return Value(value=self.host.call("counter:increment", amount))

    def describe(self) -> Descriptions:
        return Descriptions(descriptions=list(self.host.call("counter:describe")))

    def notify(self, *, value: int) -> Notification:
        self.host.call("counter:changed", value)
        return Notification(notified=True)

    def run(self, *, amount: int = 1) -> Value:
        return Value(value=self.host.call("client:run", amount))

    def operations(self) -> tuple[Operation, ...]:
        return (
            Operation("increment", "调用 counter:increment。", Amount, Value, self.increment, {"amount": 3}),
            Operation("describe", "收集全部 counter:describe 返回值。", Empty, Descriptions, self.describe, {}),
            Operation(
                "notify",
                "通知 counter:changed，记录历史与通知次数。",
                Value,
                Notification,
                self.notify,
                {"value": 6},
            ),
            Operation(
                "run",
                "调用 client:run，增量后发送通知；需要启用 extension。",
                Amount,
                Value,
                self.run,
                {"amount": 3},
            ),
            Operation("state", "读取当前状态的结构化快照。", Empty, State, self.state, {}),
            Operation(
                "reset",
                "创建独立 Host，清空状态并选择是否启用扩展。",
                Reset,
                State,
                self.reset,
                {"extension": True},
            ),
        )


def create() -> tuple[Operation, ...]:
    return KernelSession().operations()


MODULE = Module(
    "kernel",
    "真实 aurora_kernel 宿主；默认启用双倍增量扩展，状态保留至 reset 或退出。",
    create,
)

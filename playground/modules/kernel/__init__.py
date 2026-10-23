"""Kernel 声明独立 Host 的配置与操作，不维护自己的实例或记录循环。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import Field

from playground.modules.kernel.environment import specification
from playground.modules.kernel.fixtures import client, counter
from playground.modules.kernel.fixtures import extension as counter_extension
from playground.protocol import Empty, Model, Module, Operation

if TYPE_CHECKING:
    from aurora_kernel import Host


class Amount(Model):
    amount: int = Field(default=1, description="本次增量；启用 extension 时由高优先级实现乘以 2")


class Value(Model):
    value: int


class Descriptions(Model):
    descriptions: list[str]


class Notification(Model):
    notified: bool


def increment(host: Host, *, amount: int = 1) -> Value:
    return Value(value=host.call("counter:increment", amount))


def describe(host: Host) -> Descriptions:
    return Descriptions(descriptions=list(host.call("counter:describe")))


def notify(host: Host, *, value: int) -> Notification:
    host.call("counter:changed", value)
    return Notification(notified=True)


def run(host: Host, *, amount: int = 1) -> Value:
    return Value(value=host.call("client:run", amount))


SPEC = specification(
    (counter, counter_extension, client),
    isolated=True,
    operations=(
        Operation("increment", "调用 counter:increment。", Amount, Value, increment, {"amount": 3}, replayable=True),
        Operation("describe", "收集 counter:describe 返回值。", Empty, Descriptions, describe, {}, record=False),
        Operation("notify", "通知 counter:changed。", Value, Notification, notify, {"value": 6}, replayable=True),
        Operation("run", "递增并通知；需要 client。", Amount, Value, run, {"amount": 3}, replayable=True),
    ),
)

MODULE = Module("kernel", "独立 Kernel Host：模块组合、真实路由、ctx 快照与隔离复现。", workspace=SPEC)

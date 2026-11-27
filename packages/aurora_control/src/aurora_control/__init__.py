"""内置控制插件：显式连接实例，以 ctx 共享业务数据。"""

from aurora_core.components import ComponentFactory, InstanceExport
from aurora_core.ctx import StateKey
from aurora_core.declarations import plug_id
from aurora_core.discovery import Plugin
from aurora_core.hooks import HookSlot

from . import _meta
from ._meta import CONTROL_STATE
from .components import Branch, Controller, LoopLimitExceeded, Parallel, Serial, While
from .execution import (
    ExecutionLink,
    ExecutionPlug,
    ExecutionRequest,
    ExecutionSlot,
    InstanceStateBinding,
    StateBinding,
    _accept_execution,
    component_entries,
    execution_slot_entry,
)


def _serial(*, ctx, hooks, instance_id, states):
    return Serial(
        ctx, ExecutionSlot(_meta.SERIAL, hooks, instance_id=instance_id, states=states, slot_id=_meta.SERIAL_CHILDREN)
    )


def _serial_exports(instance: Serial) -> InstanceExport:
    return InstanceExport(
        plugs={
            _meta.SERIAL_EXECUTE: ExecutionPlug(
                _meta.SERIAL,
                instance.execute,
                instance.slot.states,
                instance.slot.schema,
                instance_id=instance.slot.instance_id,
                port_id=plug_id(instance.execute),
            )
        },
        slots={_meta.SERIAL_CHILDREN: instance.slot},
    )


def plugin() -> Plugin:
    """登记控制定义；Serial 显式导出实际执行端口，不建立实例连接。"""
    targets = {_meta.CONTROL_STATE: StateKey()}
    for symbol, component in (
        ("CONTROL", Controller),
        ("SERIAL", Serial),
        ("BRANCH", Branch),
        ("WHILE", While),
        ("PARALLEL", Parallel),
    ):
        targets[getattr(_meta, symbol)] = component
        targets[getattr(_meta, symbol + "_CHILDREN")] = HookSlot(_accept_execution)
        if component is not Serial:
            targets[getattr(_meta, symbol + "_EXECUTE")] = component.execute
    return _meta.control_plugin(
        targets=targets,
        components={"serial": ComponentFactory(_serial, _serial_exports, (Serial.execute,))},
    )


__all__ = [
    "CONTROL_STATE",
    "Branch",
    "Controller",
    "ExecutionLink",
    "ExecutionPlug",
    "ExecutionRequest",
    "ExecutionSlot",
    "InstanceStateBinding",
    "LoopLimitExceeded",
    "Parallel",
    "Serial",
    "StateBinding",
    "While",
    "component_entries",
    "execution_slot_entry",
    "plugin",
]

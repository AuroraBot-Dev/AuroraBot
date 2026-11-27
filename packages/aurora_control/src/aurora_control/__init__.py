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


def _factory(component, symbol, *, parameters=(), inputs=()):
    definition = getattr(_meta, symbol)
    children = getattr(_meta, symbol + "_CHILDREN")
    execute = getattr(_meta, symbol + "_EXECUTE")

    def create(*, ctx, hooks, instance_id, states, options):
        slot = ExecutionSlot(definition, hooks, instance_id=instance_id, states=states, slot_id=children)
        return component(ctx, slot, **{name: options[name] for name in parameters})

    def export(instance):
        return InstanceExport(
            plugs={
                execute: ExecutionPlug(
                    definition,
                    instance.execute,
                    instance.slot.states,
                    instance.slot.schema,
                    instance_id=instance.slot.instance_id,
                    port_id=plug_id(instance.execute),
                )
            },
            slots={children: instance.slot},
        )

    def bind(instance, resources):
        for name in inputs:
            setattr(instance, name, resources[name])

    return ComponentFactory(create, export, (component.execute,), bind if inputs else None)


def plugin() -> Plugin:
    """导出四种控制组件；分支选择与循环条件借用显式资源，不建立实例连接。"""
    targets = {_meta.CONTROL_STATE: StateKey(), _meta.CONTROL_EXECUTE: Controller.execute}
    for symbol, component in (
        ("CONTROL", Controller),
        ("SERIAL", Serial),
        ("BRANCH", Branch),
        ("WHILE", While),
        ("PARALLEL", Parallel),
    ):
        targets[getattr(_meta, symbol)] = component
        targets[getattr(_meta, symbol + "_CHILDREN")] = HookSlot(_accept_execution)
    return _meta.control_plugin(
        targets=targets,
        components={
            "serial": _factory(Serial, "SERIAL"),
            "branch": _factory(Branch, "BRANCH", inputs=("select",)),
            "while": _factory(While, "WHILE", parameters=("max_iterations",), inputs=("condition",)),
            "parallel": _factory(Parallel, "PARALLEL", parameters=("concurrency",)),
        },
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

"""读取集中装配配置，按显式组件导出建立生命周期连接。"""

import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from types import MethodType
from typing import Any, cast

from aurora_core.ctx import Context
from aurora_core.declarations import plug_id
from aurora_core.discovery import Plugin
from aurora_core.hooks import HookConnections
from aurora_core.ids import Id
from aurora_core.lifecycle import CLEAN, CONFIG, PREPARE, START, STOP, LifecycleComponent
from aurora_core.registry import DefinitionRegistry
from aurora_core.storage import StorageService

from .schema import ConfigSchema
from .templates import read_toml

_ENDPOINT = {
    "type": "object",
    "required": ["instance", "id"],
    "additionalProperties": False,
    "properties": {"instance": {"type": "string", "minLength": 1}, "id": {"type": "string", "format": "aurora-id"}},
}
ASSEMBLY_SCHEMA = ConfigSchema(
    {
        "type": "object",
        "required": ["schema_version", "plugins", "instances"],
        "additionalProperties": False,
        "properties": {
            "schema_version": {"const": 1},
            "plugins": {"type": "array", "items": {"type": "string", "minLength": 1}, "uniqueItems": True},
            "instances": {
                "type": "object",
                "additionalProperties": {
                    "type": "object",
                    "required": ["plugin", "component"],
                    "additionalProperties": False,
                    "properties": {
                        "plugin": {"type": "string"},
                        "component": {"type": "string"},
                        "depends_on": {"type": "array", "items": {"type": "string"}, "default": []},
                    },
                },
            },
            "connections": {
                "type": "array",
                "default": [],
                "items": {
                    "type": "object",
                    "required": ["plug", "slot"],
                    "additionalProperties": False,
                    "properties": {"plug": _ENDPOINT, "slot": _ENDPOINT, "priority": {"type": "integer", "default": 0}},
                },
            },
        },
    }
)


@dataclass(frozen=True)
class AssemblyPlan:
    """已校验的装配输入；实例化之前不运行组件方法。"""

    plugins: tuple[str, ...]
    instances: Mapping[str, Any]
    connections: Sequence[Mapping[str, Any]]

    @classmethod
    def parse(cls, value: object) -> "AssemblyPlan":
        data = cast(dict[str, Any], ASSEMBLY_SCHEMA.parse(value))
        return cls(tuple(data["plugins"]), data["instances"], data["connections"])

    def assemble(self, plugins: Sequence[Plugin], services: Mapping[str, Any]) -> tuple[LifecycleComponent, ...]:
        """首轮支持无参数方法插头接入 core 的五个生命周期槽。"""
        enabled = {plugin.name: plugin for plugin in plugins if plugin.name in self.plugins}
        missing = set(self.plugins) - enabled.keys()
        if missing:
            raise ValueError(f"装配缺少已启用插件：{sorted(missing)}")
        components = []
        plugs = {}
        for name, spec in self.instances.items():
            export = enabled[spec["plugin"]].components[spec["component"]]
            factory = export.factory
            instance = factory.create(**{key: services[key] for key in export.inject})
            plugs[name] = {plug_id(method): MethodType(method, instance) for method in factory.plugs}
            components.append(
                LifecycleComponent(
                    name,
                    tuple(spec["depends_on"]),
                    MethodType(factory.stop_accepting, instance) if factory.stop_accepting is not None else None,
                )
            )
        hooks: HookConnections = services["hooks"]
        for connection in self.connections:
            source, destination = connection["plug"], connection["slot"]
            slot = Id(destination["id"])
            if destination["instance"] not in self.instances:
                raise ValueError(f"插槽实例不存在：{destination['instance']}")
            if slot not in (CONFIG, PREPARE, START, STOP, CLEAN):
                raise ValueError(f"本阶段集中装配仅支持 core 生命周期插槽：{slot}")
            identity = Id(source["id"])
            hooks.connect(
                slot,
                identity,
                slot_instance=destination["instance"],
                handler_instance=source["instance"],
                target=plugs[source["instance"]][identity],
                priority=connection["priority"],
            )
        return tuple(components)


def read_assembly(path: Path) -> AssemblyPlan:
    """在插件发现之前读取，错误保留文件来源。"""
    try:
        return AssemblyPlan.parse(read_toml(path.resolve()))
    except (ValueError, TypeError) as error:
        raise ValueError(f"装配配置 {path}：{error}") from None


def configuration_component(
    registry: DefinitionRegistry, ctx: Context, hooks: HookConnections, storage: StorageService
) -> LifecycleComponent:
    """程序化宿主显式选用配置服务预设；文件装配模式由自己的清单决定是否创建它。"""
    from .service import plugin

    plan = AssemblyPlan.parse(
        tomllib.loads(files("aurora_config").joinpath("assembly.toml").read_text(encoding="utf-8"))
    )
    (component,) = plan.assemble([plugin()], {"registry": registry, "ctx": ctx, "hooks": hooks, "storage": storage})
    return component

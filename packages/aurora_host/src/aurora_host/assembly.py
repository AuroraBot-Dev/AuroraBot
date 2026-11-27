"""读取集中装配配置，按显式组件导出建立生命周期连接。"""

import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from importlib.resources import files
from pathlib import Path
from typing import Any, cast

from aurora_config.schema import ConfigSchema
from aurora_config.templates import read_toml
from aurora_control import ExecutionPlug, ExecutionSlot, InstanceStateBinding, StateBinding
from aurora_core.components import ComponentInstance, InstanceExport
from aurora_core.ctx import Context
from aurora_core.discovery import Plugin
from aurora_core.hooks import HookConnection, HookConnections
from aurora_core.ids import Id
from aurora_core.lifecycle import CLEAN, CONFIG, PREPARE, START, STOP, LifecycleComponent
from aurora_core.registry import DefinitionRegistry
from aurora_core.storage import StorageService

_ENDPOINT = {
    "type": "object",
    "required": ["instance", "id"],
    "additionalProperties": False,
    "properties": {"instance": {"type": "string", "minLength": 1}, "id": {"type": "string", "format": "aurora-id"}},
}
_RESOURCE = {
    "type": "object",
    "required": ["instance", "export"],
    "additionalProperties": False,
    "properties": {"instance": {"type": "string"}, "export": {"type": "string"}},
}
ASSEMBLY_SCHEMA = ConfigSchema(
    {
        "type": "object",
        "required": ["schema_version", "plugins", "instances"],
        "additionalProperties": False,
        "properties": {
            "schema_version": {"const": 2},
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
                        "options": {"type": "object", "default": {}},
                        "resources": {
                            "type": "object",
                            "default": {},
                            "additionalProperties": {
                                "oneOf": [_RESOURCE, {"type": "object", "additionalProperties": _RESOURCE}]
                            },
                        },
                        "states": {
                            "type": "object",
                            "default": {},
                            "additionalProperties": {
                                "type": "object",
                                "required": ["key", "scope"],
                                "additionalProperties": False,
                                "properties": {
                                    "key": {"type": "string", "format": "aurora-id"},
                                    "scope": {"enum": ["instance", "run"]},
                                    "location": {
                                        "type": "object",
                                        "additionalProperties": {"type": "string"},
                                        "default": {},
                                    },
                                },
                            },
                        },
                        "depends_on": {"type": "array", "items": {"type": "string"}, "default": []},
                    },
                },
            },
            "collection_connections": {
                "type": "array",
                "default": [],
                "items": {
                    "type": "object",
                    "required": ["collection", "slot"],
                    "additionalProperties": False,
                    "properties": {
                        "collection": {"type": "string"},
                        "slot": _ENDPOINT,
                        "priority": {"type": "integer", "default": 0},
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

    collection_connections: Sequence[Mapping[str, Any]] = ()

    @classmethod
    def parse(cls, value: object) -> "AssemblyPlan":
        data = cast(dict[str, Any], ASSEMBLY_SCHEMA.parse(value))
        return cls(tuple(data["plugins"]), data["instances"], data["connections"], data["collection_connections"])

    def assemble(self, plugins: Sequence[Plugin], services: Mapping[str, Any]) -> "RuntimeGraph":
        """先创建并显式导出所有实例，再绑定资源、连接方法与执行端口。"""
        enabled = {plugin.name: plugin for plugin in plugins if plugin.name in self.plugins}
        instances = {}
        components = []
        connections = []
        members = {}

        def publish(collection, exports):
            members[collection] = exports
            for rule in self.collection_connections:
                if rule["collection"] != collection:
                    continue
                destination = rule["slot"]
                slot = instances[destination["instance"]].exports.slots[Id(destination["id"])]
                for member in exports.values():
                    for plug in member.plugs.values():
                        link = slot.connect(plug, priority=rule["priority"])
                        connections.append(link.connection)

        for name, spec in self.instances.items():
            export = enabled[spec["plugin"]].components[spec["component"]]
            states = {
                role: (InstanceStateBinding if binding["scope"] == "instance" else StateBinding)(
                    Id(binding["key"]), tuple(sorted(binding["location"].items()))
                )
                for role, binding in spec["states"].items()
            }
            options = spec["options"]
            if export.declaration.options is not None:
                options = ConfigSchema(export.declaration.options).parse(options)
            component = export.create(
                dict(services, publish_members=lambda members, owner=name: publish(owner, members)),
                instance_id=name,
                options=options,
                states=states,
            )
            instances[name] = component
            components.append(LifecycleComponent(name, tuple(spec["depends_on"]), component.exports.stop_accepting))
        for name, spec in self.instances.items():
            instances[name].bind(
                {
                    role: (
                        {
                            key: instances[item["instance"]].exports.resources[item["export"]]
                            for key, item in reference.items()
                        }
                        if role in instances[name].declaration.resource_maps
                        else instances[reference["instance"]].exports.resources[reference["export"]]
                    )
                    for role, reference in spec["resources"].items()
                }
            )
        hooks: HookConnections = services["hooks"]
        for connection in self.connections:
            source, destination = connection["plug"], connection["slot"]
            identity, slot_id = Id(source["id"]), Id(destination["id"])
            target = instances[source["instance"]].exports.plugs[identity]
            owner = instances[destination["instance"]]
            slot = None if slot_id in (CONFIG, PREPARE, START, STOP, CLEAN) else owner.exports.slots[slot_id]
            if isinstance(slot, ExecutionSlot):
                link = slot.connect(cast(ExecutionPlug, target), priority=connection["priority"])
                connections.append(link.connection)
            else:
                connections.append(
                    hooks.connect(
                        slot_id,
                        identity,
                        slot_instance=destination["instance"],
                        handler_instance=source["instance"],
                        target=target,
                        priority=connection["priority"],
                    )
                )
        return RuntimeGraph(instances, tuple(components), connections, members)


@dataclass(frozen=True)
class RuntimeGraph:
    """本次装配的实际对象与生命周期组件；连接保存在同一宿主的 hooks 中。"""

    instances: Mapping[str, ComponentInstance]
    components: tuple[LifecycleComponent, ...]
    connections: list[HookConnection] = field(default_factory=list)
    members: dict[str, Mapping[str, InstanceExport]] = field(default_factory=dict)


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
    from aurora_config.service import plugin

    plan = AssemblyPlan.parse(
        tomllib.loads(files("aurora_config").joinpath("assembly.toml").read_text(encoding="utf-8"))
    )
    (component,) = plan.assemble(
        [plugin()], {"registry": registry, "ctx": ctx, "hooks": hooks, "storage": storage}
    ).components
    return component

"""组件显式导出与清单绑定；不读取文件或建立运行连接。"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from .declarations import plug_id
from .ids import Id
from .registry import RegistryEntry

if TYPE_CHECKING:
    from .discovery import Plugin


@dataclass(frozen=True)
class InstanceExport:
    """实例显式导出的实际端口与资源；core 不解释执行端口的具体类型。"""

    plugs: Mapping[Id, Callable[..., Any]] = field(default_factory=dict)
    slots: Mapping[Id, object] = field(default_factory=dict)
    resources: Mapping[str, object] = field(default_factory=dict)
    stop_accepting: Callable[[], object] | None = None


@dataclass(frozen=True)
class ComponentFactory:
    """创建、显式导出与资源绑定均由插件实现；plugs 提供静态方法定义。"""

    create: Callable[..., Any]
    export: Callable[[Any], InstanceExport]
    plugs: tuple[Callable[..., Any], ...] = ()
    bind: Callable[[Any, Mapping[str, Any]], None] | None = None


@dataclass(frozen=True)
class ComponentInstance:
    """已创建和导出的组件；资源在全部实例创建后绑定。"""

    instance: Any
    exports: InstanceExport
    factory: ComponentFactory
    declaration: "ComponentDeclaration"

    def bind(self, resources: Mapping[str, object]) -> None:
        selected = {name: resources[name] for name in self.declaration.inputs}
        selected.update({name: resources[name] for name in self.declaration.optional_inputs if name in resources})
        selected.update({name: resources.get(name, {}) for name in self.declaration.resource_maps})
        if self.factory.bind is not None:
            self.factory.bind(self.instance, selected)


@dataclass(frozen=True)
class ComponentExport:
    """清单声明与代码工厂；构造入口只接收清单列出的服务和参数。"""

    factory: ComponentFactory
    declaration: "ComponentDeclaration"

    def create(
        self,
        services: Mapping[str, Any],
        *,
        instance_id: str,
        options: Mapping[str, object] | None = None,
        states: Mapping[str, object] | None = None,
    ) -> ComponentInstance:
        states = {} if states is None else states
        for role in self.declaration.states:
            states[role]
        arguments = dict(services, instance_id=instance_id, options={} if options is None else options, states=states)
        instance = self.factory.create(**{name: arguments[name] for name in self.declaration.inject})
        exports = self.factory.export(instance)
        if (
            exports.plugs.keys() != set(self.declaration.plugs)
            or exports.slots.keys() != set(self.declaration.slots)
            or exports.resources.keys() != set(self.declaration.resources)
        ):
            raise ValueError("组件实例的插头、插槽或资源导出与清单不一致")
        return ComponentInstance(instance, exports, self.factory, self.declaration)


@dataclass(frozen=True)
class Definition:
    """生成模块持有的公开定义；target 由插件实现提供。"""

    id: Id
    kind: str
    provider: str
    register_to: Id | None = None
    interface: object | None = None

    def bind(self, target: object) -> RegistryEntry:
        return RegistryEntry(
            self.id, self.kind, target, self.provider, register_to=self.register_to, interface=self.interface
        )


@dataclass(frozen=True)
class DynamicDefinition:
    """清单声明的动态身份范围；运行目录提供成员名称和实现。"""

    id_root: str
    kind: str
    provider: str
    register_to: Id

    def bind(self, name: str, target: object) -> RegistryEntry:
        return RegistryEntry(
            Id(f"{self.id_root}/{name}"), self.kind, target, self.provider, register_to=self.register_to
        )


@dataclass(frozen=True)
class ComponentDeclaration:
    """组件端口、状态角色、资源输入/输出和构造参数契约。"""

    inject: tuple[str, ...] = ()
    plugs: tuple[Id, ...] = ()
    slots: tuple[Id, ...] = ()
    states: tuple[str, ...] = ()
    optional_states: tuple[str, ...] = ()
    resources: tuple[str, ...] = ()
    inputs: tuple[str, ...] = ()
    optional_inputs: tuple[str, ...] = ()
    resource_maps: tuple[str, ...] = ()
    options: object | None = None


@dataclass(frozen=True)
class PluginDeclaration:
    """清单生成的插件声明；只在显式调用 bind 时收集实现。"""

    name: str
    definitions: tuple[Definition, ...]
    requires: tuple[str, ...] = ()
    components: Mapping[str, ComponentDeclaration] = field(default_factory=dict)

    def bind(self, *, targets: Mapping[Id, object], components: Mapping[str, ComponentFactory]) -> "Plugin":
        from .discovery import Plugin

        if components.keys() != self.components.keys():
            raise ValueError(f"插件 {self.name} 的组件导出与清单不一致")
        implementations = dict(targets)
        exports = {}
        for name, declaration in self.components.items():
            factory = components[name]
            methods = {plug_id(method): method for method in factory.plugs}
            if len(methods) != len(factory.plugs) or methods.keys() != set(declaration.plugs):
                raise ValueError(f"组件 {name} 的插头导出与清单不一致")
            for identity, method in methods.items():
                if identity in implementations and implementations[identity] is not method:
                    raise ValueError(f"插头存在多个实现：{identity}")
                implementations[identity] = method
            if (
                declaration.inputs or declaration.optional_inputs or declaration.resource_maps
            ) and factory.bind is None:
                raise ValueError(f"组件 {name} 声明了资源输入但没有 bind")
            exports[name] = ComponentExport(factory, declaration)
        if implementations.keys() != {definition.id for definition in self.definitions}:
            raise ValueError(f"插件 {self.name} 的定义实现与清单不一致")
        return Plugin(
            self.name,
            tuple(definition.bind(implementations[definition.id]) for definition in self.definitions),
            self.requires,
            exports,
        )

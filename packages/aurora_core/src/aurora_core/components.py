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
class ComponentFactory:
    """同步创建组件；导出未绑定方法和组件自己的停止接收动作。"""

    create: Callable[..., Any]
    plugs: tuple[Callable[..., Any], ...] = ()
    stop_accepting: Callable[..., object] | None = None


@dataclass(frozen=True)
class ComponentExport:
    """清单声明的注入服务与代码工厂。"""

    factory: ComponentFactory
    inject: tuple[str, ...] = ()


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
class ComponentDeclaration:
    """组件导出的插头身份和所需宿主服务。"""

    inject: tuple[str, ...] = ()
    plugs: tuple[Id, ...] = ()


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
            exports[name] = ComponentExport(factory, declaration.inject)
        if implementations.keys() != {definition.id for definition in self.definitions}:
            raise ValueError(f"插件 {self.name} 的定义实现与清单不一致")
        return Plugin(
            self.name,
            tuple(definition.bind(implementations[definition.id]) for definition in self.definitions),
            self.requires,
            exports,
        )

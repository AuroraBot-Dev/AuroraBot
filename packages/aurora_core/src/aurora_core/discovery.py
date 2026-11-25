"""显式选择插件并收集定义；entry point 仅承担发现职责。"""

from collections.abc import Iterable
from dataclasses import dataclass
from importlib.metadata import EntryPoint, entry_points

from .registry import DefinitionRegistry, RegistryEntry

ENTRY_POINT_GROUP = "aurora.plugins"


@dataclass(frozen=True)
class Plugin:
    """最小插件清单；requires 引用必须同时启用的插件名称。"""

    name: str
    entries: tuple[RegistryEntry, ...] = ()
    requires: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("插件名称不能为空")


def load_plugins(
    *, explicit: Iterable[Plugin] = (), enabled: Iterable[str] = (), available: Iterable[EntryPoint] | None = None
) -> tuple[Plugin, ...]:
    """显式清单优先；仅加载 enabled 中的 entry point，不隐式启用依赖。

    entry point 指向无参数工厂，返回 Plugin，名称须与 entry point 一致。
    同名显式清单及所选 entry point 歧义均报错；导入失败附发现来源。
    """
    selected: dict[str, Plugin] = {}
    for plugin in explicit:
        if plugin.name in selected:
            raise ValueError(f"显式插件重复：{plugin.name}")
        selected[plugin.name] = plugin
    requested = set(enabled) - selected.keys()
    points = tuple(available if available is not None else entry_points(group=ENTRY_POINT_GROUP)) if requested else ()
    for name in sorted(requested):
        matches = [point for point in points if point.group == ENTRY_POINT_GROUP and point.name == name]
        if len(matches) != 1:
            raise ValueError(f"插件入口缺失或存在歧义：{name}，匹配数：{len(matches)}")
        point = matches[0]
        try:
            plugin = point.load()()
            if not isinstance(plugin, Plugin) or plugin.name != name:
                raise ValueError("工厂必须返回名称与入口一致的 Plugin")
        except Exception as error:
            raise RuntimeError(f"插件加载失败：{name}，来源：{point.value}") from error
        selected[name] = plugin
    for plugin in selected.values():
        missing = set(plugin.requires) - selected.keys()
        if missing:
            raise ValueError(f"插件 {plugin.name} 缺少必需依赖：{', '.join(sorted(missing))}")
    return tuple(selected.values())


def register_plugins(registry: DefinitionRegistry, plugins: Iterable[Plugin]) -> None:
    """先完成全部定义收集，再原子登记；接收方检查由宿主另行执行。"""
    registry.register_many(entry for plugin in plugins for entry in plugin.entries)

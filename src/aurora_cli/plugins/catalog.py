"""把全部来源的 CLI 声明冻结为一次调用的目录，统一校验后才允许执行。"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, cast

from aurora_cli.contracts.command import CommandRegistry
from aurora_cli.plugins.configs import ConfigCatalog, relative_path
from aurora_cli.plugins.discovery import DiscoveredPlugin, default_sources
from aurora_kernel import CONSTRUCT, Context, Host, ModuleSpec, Namespace, namespace

if TYPE_CHECKING:
    import argparse
    from collections.abc import Iterable

    from aurora_cli.contracts.command import CommandBinding
    from aurora_cli.contracts.plugin import CommandContribution, ConfigContribution
    from aurora_kernel.discovery import DiscoverySource


@namespace("aurora.cli")
def _cli(_ctx: Context) -> None:
    """CLI 目录和工作目录在构造前显式注入 ctx。"""


def _unique(seen: dict[str, str], key: str, origin: str, label: str) -> None:
    if key in seen:
        raise ValueError(f"{label}重复注册：{key}（{seen[key]}；{origin}）")
    seen[key] = origin


def _config_paths(config: ConfigContribution, origin: str, seen: dict[str, str]) -> None:
    main = relative_path(config.spec.path)
    paths = {main}
    templates: set[str] = set()
    for file in config.files:
        path = relative_path(file.destination)
        if path in templates:
            raise ValueError(f"配置资源重复注册：{path}（{origin}）")
        templates.add(path)
        paths.add(path)
    for path in sorted(paths):
        for existing, other in seen.items():
            if (
                PurePosixPath(path) in PurePosixPath(existing).parents
                or PurePosixPath(existing) in PurePosixPath(path).parents
            ):
                raise ValueError(f"配置文件与目录路径冲突：{path} / {existing}（{origin}；{other}）")
        _unique(seen, path, origin, "配置路径")


def _modules(found: Iterable[DiscoveredPlugin]) -> tuple[tuple[ModuleSpec, ...], dict[str, str]]:
    modules = [_cli.spec]
    identities = {"aurora.cli": "CLI 宿主"}
    for item in found:
        if not isinstance(item, DiscoveredPlugin):
            raise TypeError("CLI 发现源必须返回 DiscoveredPlugin")
        declaration = item.plugin.module
        module = declaration.spec if isinstance(declaration, Namespace) else declaration
        _unique(identities, module.module_id, item.origin, "CLI 插件")
        modules.append(module)
    return tuple(modules), identities


@dataclass(frozen=True, slots=True)
class PluginCatalog:
    root: Path
    modules: tuple[ModuleSpec, ...]
    commands: tuple[CommandContribution, ...]
    configs: ConfigCatalog
    origins: tuple[tuple[str, str], ...]

    def registry(self) -> CommandRegistry:
        return CommandRegistry(tuple(self._binding(command) for command in self.commands))

    def _binding(self, command: CommandContribution) -> CommandBinding:
        def invoke(arguments: argparse.Namespace) -> int:
            host = Host(self.modules)
            host.ctx["aurora.cli"]["catalog"] = self
            host.ctx["aurora.cli"]["root"] = self.root
            arguments.root = self.root
            arguments.cli = self
            host.build()
            return cast("int", host.call(command.target, arguments))

        return command.spec, invoke


def load_plugins(root: Path, *, sources: Iterable[DiscoverySource] | None = None) -> PluginCatalog:
    """无全局缓存；不同工作目录及每次入口调用各有独立声明与 ctx。"""
    root = root.resolve()
    selected_sources = default_sources(root) if sources is None else sources
    found = tuple(item for source in selected_sources for item in source.discover())
    modules, identities = _modules(found)
    # Host 在构造函数中完成版本、依赖、环与 hook 冲突检查，不运行初始化函数。
    host = Host(modules)
    active = {module.module_id for module in host.resolution.construction}
    commands: list[CommandContribution] = []
    configs: list[ConfigContribution] = []
    command_names: dict[str, str] = {}
    config_names: dict[str, str] = {}
    config_paths: dict[str, str] = {}
    for item in found:
        plugin, origin = item.plugin, item.origin
        module = plugin.module.spec if isinstance(plugin.module, Namespace) else plugin.module
        if module.module_id not in active:
            continue
        if any(phase != CONSTRUCT for phase in module.hooks):
            raise ValueError(f"CLI 插件使用同步构造，资源应由命令执行器管理：{origin}")
        for command in plugin.commands:
            name = command.spec.get("name")
            if not isinstance(name, str) or not name.strip():
                raise ValueError(f"命令名称不能为空：{origin}")
            _unique(command_names, name, origin, "命令")
            commands.append(replace(command, spec=deepcopy(command.spec)))
        for config in plugin.configs:
            _unique(config_names, config.spec.name, origin, "配置")
            _config_paths(config, origin, config_paths)
            configs.append(replace(config, files=tuple(config.files)))
    points = {point.name: point.mode for module in host.resolution.construction for point in module.points}
    for command in commands:
        if command.target not in points:
            raise ValueError(f"命令 {command.spec['name']} 的调用点不存在：{command.target}")
        if points[command.target] != "single":
            raise ValueError(f"命令调用点必须使用 single 模式：{command.target}")
    catalog = PluginCatalog(
        root,
        tuple(modules),
        tuple(commands),
        ConfigCatalog(tuple(sorted(configs, key=lambda item: item.spec.name))),
        tuple(identities.items()),
    )
    catalog.registry()
    return catalog

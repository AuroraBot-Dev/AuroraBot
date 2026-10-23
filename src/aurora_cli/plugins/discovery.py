"""CLI 只选择来源与声明协议，文件导入和安装入口枚举复用通用内核。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from aurora_cli.contracts.plugin import CliPlugin
from aurora_kernel.discovery import DirectorySource, EntryPointSource, PackageSource

if TYPE_CHECKING:
    from pathlib import Path

    from aurora_kernel.discovery import DiscoverySource


@dataclass(frozen=True, slots=True)
class DiscoveredPlugin:
    plugin: CliPlugin
    origin: str


def plugin_spec(source: object, origin: str) -> DiscoveredPlugin:
    candidate = getattr(source, "MODULE", source)
    if not isinstance(candidate, CliPlugin):
        raise TypeError(f"CLI 插件必须导出 CliPlugin 类型的 MODULE：{origin}")
    return DiscoveredPlugin(candidate, origin)


def default_sources(root: Path) -> tuple[DiscoverySource, ...]:
    return (
        PackageSource("aurora_cli.commands", extract=plugin_spec, entry_module=None),
        PackageSource("aurora_cli.configs", extract=plugin_spec, entry_module=None),
        DirectorySource(root / "extensions" / "cli", extract=plugin_spec),
        EntryPointSource("aurora_cli_plugin", extract=plugin_spec),
    )

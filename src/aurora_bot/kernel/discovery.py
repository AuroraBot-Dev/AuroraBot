"""Bot 发现适配：同时接受领域声明和通用 namespace 声明。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from aurora_bot.kernel.declaration import ModuleSpec
from aurora_kernel.discovery import DirectorySource as HostDirectorySource
from aurora_kernel.discovery import DiscoverySource, PackageSource, StaticSource, module_spec
from aurora_kernel.discovery import EntryPointSource as HostEntryPointSource

if TYPE_CHECKING:
    from pathlib import Path

    from aurora_kernel.declaration import ModuleSpec as HostModule

__all__ = ["BuiltinSource", "DirectorySource", "DiscoverySource", "EntryPointSource", "StaticSource"]


class BuiltinSource(PackageSource):
    """读取随安装发布的 Bot 功能包。"""

    def __init__(self, package: str = "aurora_bot") -> None:
        super().__init__(package, extract=_module_spec)


class DirectorySource(HostDirectorySource):
    def __init__(self, directory: Path) -> None:
        super().__init__(directory, extract=_module_spec)


class EntryPointSource(HostEntryPointSource):
    """沿用宿主的入口枚举，只补充 Bot 声明提取。"""

    def __init__(self, group: str = "aurorabot_plugin") -> None:
        super().__init__(group, extract=_module_spec)


def _module_spec(source: object, origin: str) -> ModuleSpec | HostModule:
    candidate = getattr(source, "MODULE", source)
    if isinstance(candidate, ModuleSpec):
        return candidate
    return module_spec(candidate, origin)

"""组合微内核：模块声明、依赖解析、装配与统一生命周期。"""

from src.kernel.compose import (
    ContributionBinding,
    InstanceBinding,
    compose,
    compose_managed,
)
from src.kernel.context import Assembly, Capabilities, ModuleContext
from src.kernel.declaration import AsyncCleanup, ModuleSpec, module
from src.kernel.discovery import (
    BuiltinSource,
    DirectorySource,
    DiscoverySource,
    EntryPointSource,
    StaticSource,
)
from src.kernel.lifecycle import ManagedAssembly
from src.kernel.resolve import Resolution, resolve

__all__ = [
    "Assembly",
    "AsyncCleanup",
    "BuiltinSource",
    "Capabilities",
    "ContributionBinding",
    "DirectorySource",
    "DiscoverySource",
    "EntryPointSource",
    "InstanceBinding",
    "ManagedAssembly",
    "ModuleContext",
    "ModuleSpec",
    "Resolution",
    "StaticSource",
    "compose",
    "compose_managed",
    "module",
    "resolve",
]

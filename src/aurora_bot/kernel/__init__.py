"""组合微内核：模块声明、依赖解析、装配与统一生命周期。"""

from aurora_bot.contracts.module_manifest import ModuleManifest
from aurora_bot.kernel.api import KERNEL_API_VERSION
from aurora_bot.kernel.compose import (
    ContributionBinding,
    InstanceBinding,
    compose,
    compose_managed,
)
from aurora_bot.kernel.context import Assembly, Capabilities, ModuleContext
from aurora_bot.kernel.declaration import AsyncCleanup, ModuleSpec, module
from aurora_bot.kernel.discovery import (
    BuiltinSource,
    DirectorySource,
    DiscoverySource,
    EntryPointSource,
    StaticSource,
)
from aurora_bot.kernel.failures import ModuleLifecycleError
from aurora_bot.kernel.lifecycle import ManagedAssembly
from aurora_bot.kernel.phase import (
    ACTIVATE,
    BUILTIN_PHASES,
    CLOSE,
    CONSTRUCT,
    DRAIN,
    PREPARE,
    READY,
    RUN,
    Ordering,
    Phase,
    PhaseKind,
)
from aurora_bot.kernel.resolve import PhaseStep, Resolution, resolve

__all__ = [
    "ACTIVATE",
    "BUILTIN_PHASES",
    "CLOSE",
    "CONSTRUCT",
    "DRAIN",
    "KERNEL_API_VERSION",
    "PREPARE",
    "READY",
    "RUN",
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
    "ModuleLifecycleError",
    "ModuleManifest",
    "ModuleSpec",
    "Ordering",
    "Phase",
    "PhaseKind",
    "PhaseStep",
    "Resolution",
    "StaticSource",
    "compose",
    "compose_managed",
    "module",
    "resolve",
]

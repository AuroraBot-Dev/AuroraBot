"""组合微内核：模块声明、依赖解析、装配与统一生命周期。"""

from aurorabot.contracts.module_manifest import ModuleManifest
from aurorabot.kernel.api import KERNEL_API_VERSION
from aurorabot.kernel.compose import (
    ContributionBinding,
    InstanceBinding,
    compose,
    compose_managed,
)
from aurorabot.kernel.context import Assembly, Capabilities, ModuleContext
from aurorabot.kernel.declaration import AsyncCleanup, ModuleSpec, module
from aurorabot.kernel.discovery import (
    BuiltinSource,
    DirectorySource,
    DiscoverySource,
    EntryPointSource,
    StaticSource,
)
from aurorabot.kernel.failures import ModuleLifecycleError
from aurorabot.kernel.lifecycle import ManagedAssembly
from aurorabot.kernel.phase import (
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
from aurorabot.kernel.resolve import PhaseStep, Resolution, resolve

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

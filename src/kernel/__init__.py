"""组合微内核：模块声明、依赖解析、装配与统一生命周期。"""

from src.contracts.module_manifest import ModuleManifest
from src.kernel.api import KERNEL_API_VERSION
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
from src.kernel.failures import ModuleLifecycleError
from src.kernel.lifecycle import ManagedAssembly
from src.kernel.phase import (
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
from src.kernel.resolve import PhaseStep, Resolution, resolve

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

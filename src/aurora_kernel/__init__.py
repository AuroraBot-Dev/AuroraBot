"""namespace、hook 与共享 ctx 驱动的通用模块宿主。"""

from aurora_kernel.context import Change, Context, ContextConflictError
from aurora_kernel.declaration import Callpoint, Hook, Manifest, ModuleSpec, Namespace, namespace
from aurora_kernel.failures import ModuleLifecycleError
from aurora_kernel.host import Host
from aurora_kernel.phase import ACTIVATE, CLOSE, CONSTRUCT, DRAIN, PREPARE, READY, RUN, Ordering, Phase, PhaseKind

__all__ = [
    "ACTIVATE",
    "CLOSE",
    "CONSTRUCT",
    "DRAIN",
    "PREPARE",
    "READY",
    "RUN",
    "Callpoint",
    "Change",
    "Context",
    "ContextConflictError",
    "Hook",
    "Host",
    "Manifest",
    "ModuleLifecycleError",
    "ModuleSpec",
    "Namespace",
    "Ordering",
    "Phase",
    "PhaseKind",
    "namespace",
]
